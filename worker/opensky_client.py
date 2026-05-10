"""OpenSky Network API client – multi-backend with automatic fallback.

Tries backends in this order:
  1. requests         – different TLS stack than httpx, often bypasses filters
  2. httpx (HTTP/1.1) – fallback with curl-mimicking headers
  3. subprocess curl  – native TLS/JA3 fingerprint, most permissive (fallback)

Environment variables:
  OPENSKY_USERNAME / OPENSKY_PASSWORD – basic auth (increases rate limits)
  OPENSKY_FORCE_BACKEND  – force one backend: "curl" | "requests" | "httpx"
"""

import json
import logging
import os
import subprocess
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

# ── Circuit breaker state machine ──────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class RequestStatus(Enum):
    SUCCESS_DATA = "SUCCESS_DATA"
    SUCCESS_NO_DATA = "SUCCESS_NO_DATA"
    NETWORK_BLOCKED = "NETWORK_BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_ERROR = "AUTH_ERROR"

CIRCUIT_MAX_FAILURES = 3

_cb_state = CircuitState.CLOSED
_cb_failures = 0
_cb_reset_at = 0.0
_cb_escalation_level = 0


def _check_circuit() -> bool:
    """Returns True if request is allowed, False if circuit is OPEN (fast-fail)."""
    global _cb_state, _cb_reset_at
    if _cb_state == CircuitState.OPEN:
        if time.time() >= _cb_reset_at:
            logger.info("[Circuit HALF_OPEN] Testing connection...")
            _cb_state = CircuitState.HALF_OPEN
            return True
        else:
            logger.debug("[Circuit OPEN] Fast-failing request to save worker.")
            return False
    return True


def _on_success():
    """Resets the circuit breaker on successful connection."""
    global _cb_state, _cb_failures, _cb_escalation_level, _cb_reset_at
    if _cb_state != CircuitState.CLOSED:
        logger.info("[Circuit CLOSED] Connection restored.")
    _cb_state = CircuitState.CLOSED
    _cb_failures = 0
    _cb_escalation_level = 0
    _cb_reset_at = 0.0


def _on_fail(status: RequestStatus):
    """Handles failures and applies exponential backoff."""
    global _cb_state, _cb_failures, _cb_escalation_level, _cb_reset_at

    if status == RequestStatus.AUTH_ERROR:
        _cb_state = CircuitState.OPEN
        _cb_reset_at = time.time() + 3600
        logger.error("[Circuit OPEN] Auth Error. Pausing OpenSky for 3600s.")
        return

    if status == RequestStatus.RATE_LIMITED:
        _cb_state = CircuitState.OPEN
        _cb_reset_at = time.time() + 60
        logger.warning("[Circuit OPEN] Rate Limited. Pausing OpenSky for 60s.")
        return

    if status == RequestStatus.NETWORK_BLOCKED:
        if _cb_state == CircuitState.HALF_OPEN:
            # Failed the probe request, backoff exponentially
            _cb_state = CircuitState.OPEN
            backoff_time = min(300 * (2 ** _cb_escalation_level), 3600)
            _cb_reset_at = time.time() + backoff_time
            _cb_escalation_level += 1
            logger.warning(f"[Circuit OPEN] IP still blocked. Pausing OpenSky for {backoff_time}s")
        else:
            # Normal failure accumulation
            _cb_failures += 1
            if _cb_failures >= CIRCUIT_MAX_FAILURES:
                _cb_state = CircuitState.OPEN
                backoff_time = min(300 * (2 ** _cb_escalation_level), 3600)
                _cb_reset_at = time.time() + backoff_time
                _cb_escalation_level += 1
                logger.warning(f"[Circuit OPEN] IP Blocked. Pausing OpenSky for {backoff_time}s")


# ── Backend implementations ────────────────────────────────────────────────────

def _requests_request(url: str, auth: Optional[tuple], timeout: int) -> Tuple[RequestStatus, Optional[Any]]:
    """Use the requests library (Primary)."""
    try:
        import requests as req
        headers = {
            "User-Agent": "curl/7.88.1",
            "Accept":     "application/json",
        }
        r = req.get(url, headers=headers, auth=auth, timeout=timeout, verify=True)
        
        if r.status_code == 200:
            return RequestStatus.SUCCESS_DATA, r.json()
        if r.status_code == 404:
            return RequestStatus.SUCCESS_NO_DATA, None
        if r.status_code in (401, 403):
            return RequestStatus.AUTH_ERROR, None
        if r.status_code == 429:
            return RequestStatus.RATE_LIMITED, None
            
        logger.debug(f"[requests] HTTP {r.status_code}")
        return RequestStatus.NETWORK_BLOCKED, None
    except Exception as e:
        logger.debug(f"[requests] {type(e).__name__}: {e}")
        return RequestStatus.NETWORK_BLOCKED, None


def _httpx_request(url: str, auth: Optional[tuple], timeout: int) -> Tuple[RequestStatus, Optional[Any]]:
    """httpx with curl-mimicking settings (Secondary)."""
    try:
        import httpx
        headers = {
            "User-Agent": "curl/7.88.1",
            "Accept":     "application/json",
        }
        with httpx.Client(
            http2=False,        # Force HTTP/1.1
            timeout=timeout,
            verify=True,
            headers=headers,
        ) as client:
            r = client.get(url, auth=auth)
            
        if r.status_code == 200:
            return RequestStatus.SUCCESS_DATA, r.json()
        if r.status_code == 404:
            return RequestStatus.SUCCESS_NO_DATA, None
        if r.status_code in (401, 403):
            return RequestStatus.AUTH_ERROR, None
        if r.status_code == 429:
            return RequestStatus.RATE_LIMITED, None
            
        logger.debug(f"[httpx] HTTP {r.status_code}")
        return RequestStatus.NETWORK_BLOCKED, None
    except Exception as e:
        logger.debug(f"[httpx] {type(e).__name__}: {e}")
        return RequestStatus.NETWORK_BLOCKED, None


def _curl_request(url: str, auth: Optional[tuple], timeout: int) -> Tuple[RequestStatus, Optional[Any]]:
    """Use the system curl binary (Fallback)."""
    cmd = [
        "curl",
        "-s",                   # silent
        "-w", "%{http_code}",   # append HTTP status code at the end
        "--max-time", str(timeout),
        "--connect-timeout", "10",
        "--http1.1",            # avoid HTTP/2 negotiation issues
        "--tlsv1.2",            # consistent TLS version
        "--compressed",         # accept gzip
        "-H", "Accept: application/json",
        "-H", "User-Agent: curl/7.88.1",
    ]
    if auth:
        cmd += ["-u", f"{auth[0]}:{auth[1]}"]
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        stdout = result.stdout.strip()
        
        if len(stdout) >= 3:
            http_code = stdout[-3:]
            body = stdout[:-3].strip()
            
            if http_code == "200":
                if body:
                    try:
                        return RequestStatus.SUCCESS_DATA, json.loads(body)
                    except json.JSONDecodeError:
                        return RequestStatus.NETWORK_BLOCKED, None
                return RequestStatus.SUCCESS_NO_DATA, None
            elif http_code == "404":
                return RequestStatus.SUCCESS_NO_DATA, None
            elif http_code == "429":
                return RequestStatus.RATE_LIMITED, None
            elif http_code in ("401", "403"):
                return RequestStatus.AUTH_ERROR, None
            else:
                logger.debug(f"[curl] HTTP {http_code}")
                return RequestStatus.NETWORK_BLOCKED, None
                
        return RequestStatus.NETWORK_BLOCKED, None
    except subprocess.TimeoutExpired:
        logger.debug("[curl] subprocess timed out")
        return RequestStatus.NETWORK_BLOCKED, None
    except Exception as e:
        logger.debug(f"[curl] error: {e}")
        return RequestStatus.NETWORK_BLOCKED, None


# ── Client class ───────────────────────────────────────────────────────────────

class OpenSkyClient:
    """
    OpenSky Network REST API client with automatic backend selection and Circuit Breaker.
    """

    BASE_URL = "https://opensky-network.org/api"
    TIMEOUT  = 20   # seconds per attempt

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        rate_limit_delay: float = 10.0,
    ):
        self.username = username or os.getenv("OPENSKY_USERNAME")
        self.password = password or os.getenv("OPENSKY_PASSWORD")
        self.rate_limit_delay = 2.0 if (self.username and self.password) else rate_limit_delay
        self._last_req: float = 0.0
        self._force_backend = os.getenv("OPENSKY_FORCE_BACKEND", "").lower()
        
        self._has_curl     = self._check_curl()
        self._has_requests = self._check_requests()
        is_auth = bool(self.username and self.password)
        
        logger.info(
            f"[opensky] Client ready – auth={is_auth} delay={self.rate_limit_delay}s "
            f"timeout={self.TIMEOUT}s "
            f"backends: requests={'✓' if self._has_requests else '✗'} "
            f"httpx=✓ curl={'✓' if self._has_curl else '✗'}"
            + (f" (forced={self._force_backend})" if self._force_backend else "")
        )

    @staticmethod
    def _check_curl() -> bool:
        try:
            subprocess.run(["curl", "--version"], capture_output=True, timeout=3, check=True)
            return True
        except Exception:
            return False

    @staticmethod
    def _check_requests() -> bool:
        try:
            import requests  # noqa: F401
            return True
        except ImportError:
            return False

    def _auth(self) -> Optional[tuple]:
        if self.username and self.password:
            return (self.username, self.password)
        return None

    def _throttle(self):
        elapsed = time.time() - self._last_req
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_req = time.time()

    def _get(self, endpoint: str, params: Dict[str, Any]) -> Optional[Any]:
        """
        Executes request through state machine and backend fallbacks.
        """
        if not _check_circuit():
            return None

        self._throttle()
        url = self._build_url(endpoint, params)
        auth = self._auth()
        force = self._force_backend

        backends = []
        if force == "curl":
            backends = [("curl", _curl_request)]
        elif force == "requests":
            backends = [("requests", _requests_request)]
        elif force == "httpx":
            backends = [("httpx", _httpx_request)]
        else:
            # Auto: try in order of efficiency (CPU/Memory)
            if self._has_requests: backends.append(("requests", _requests_request))
            backends.append(("httpx", _httpx_request))
            if self._has_curl: backends.append(("curl", _curl_request))

        for name, fn in backends:
            try:
                status, data = fn(url, auth, self.TIMEOUT)
                
                if status in (RequestStatus.SUCCESS_DATA, RequestStatus.SUCCESS_NO_DATA):
                    _on_success()
                    return data
                    
                if status == RequestStatus.RATE_LIMITED:
                    _on_fail(status)
                    return None
                    
                if status == RequestStatus.AUTH_ERROR:
                    _on_fail(status)
                    return None
                    
                if status == RequestStatus.NETWORK_BLOCKED:
                    continue # Try next backend
                    
            except Exception as e:
                logger.warning(f"[opensky] {name} exception: {e}")
                continue

        # All backends failed
        _on_fail(RequestStatus.NETWORK_BLOCKED)
        logger.debug(f"[opensky] All backends failed for {endpoint}. Failure count: {_cb_failures}/{CIRCUIT_MAX_FAILURES}")
        return None

    @staticmethod
    def _build_url(endpoint: str, params: Dict[str, Any]) -> str:
        base = f"https://opensky-network.org/api/{endpoint}"
        if not params:
            return base
        qs = urllib.parse.urlencode(params)
        return f"{base}?{qs}"

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_flights_by_bounding_box(
        self,
        begin: int, end: int,
        lamin: float, lomin: float,
        lamax: float, lomax: float,
    ) -> List[Dict[str, Any]]:
        if end - begin > 7200:
            end = begin + 7200
        data = self._get("flights/area", {
            "begin": begin, "end": end,
            "lamin": lamin, "lomin": lomin,
            "lamax": lamax, "lomax": lomax,
        })
        return data if isinstance(data, list) else []

    def get_all_flights(self, begin: int, end: int) -> List[Dict[str, Any]]:
        if end - begin > 7200:
            end = begin + 7200
        data = self._get("flights/all", {"begin": begin, "end": end})
        return data if isinstance(data, list) else []

    def get_recent_flights(self, hours: int = 2) -> List[Dict[str, Any]]:
        end = int(datetime.utcnow().timestamp())
        return self.get_all_flights(end - hours * 3600, end)

    def get_state_vectors(
        self,
        lamin: Optional[float] = None, lomin: Optional[float] = None,
        lamax: Optional[float] = None, lomax: Optional[float] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if all(v is not None for v in [lamin, lomin, lamax, lomax]):
            params.update({"lamin": lamin, "lomin": lomin,
                           "lamax": lamax, "lomax": lomax})
        return self._get("states/all", params) or {}

    def test_connection(self) -> Dict[str, Any]:
        """Full diagnostic: test all backends and return results."""
        url = self._build_url("states/all", {
            "lamin": 24, "lomin": 44, "lamax": 25, "lomax": 45
        })
        auth  = self._auth()
        results = {}

        for name, fn in [
            ("requests", _requests_request),
            ("httpx",    _httpx_request),
            ("curl",     _curl_request),
        ]:
            available = (
                self._has_curl     if name == "curl"     else
                self._has_requests if name == "requests" else True
            )
            if not available:
                results[name] = {"available": False}
                continue
            t0 = time.time()
            try:
                status, data = fn(url, auth, 12)
                elapsed = round(time.time() - t0, 2)
                success = status in (RequestStatus.SUCCESS_DATA, RequestStatus.SUCCESS_NO_DATA)
                results[name] = {
                    "available": True,
                    "success":   success,
                    "status":    status.name,
                    "elapsed_s": elapsed,
                }
            except Exception as e:
                results[name] = {
                    "available": True,
                    "success": False,
                    "error": str(e),
                }

        any_success = any(v.get("success") for v in results.values())
        return {
            "any_reachable":        any_success,
            "circuit_state":        _cb_state.name,
            "consecutive_failures": _cb_failures,
            "backends":             results,
            "advice": None if any_success else (
                "OpenSky is unreachable from all HTTP backends. "
                "Possible causes: (1) Cloud/datacenter IP blocked by OpenSky. "
                "(2) Missing credentials – add OPENSKY_USERNAME + OPENSKY_PASSWORD. "
                "Solution: run the Celery worker on a non-cloud machine "
                "pointing at the same Railway Redis + PostgreSQL."
            ),
        }

    # Compat properties
    @property
    def circuit_is_open(self) -> bool:
        return _cb_state == CircuitState.OPEN

    @property
    def consecutive_failures(self) -> int:
        return _cb_failures