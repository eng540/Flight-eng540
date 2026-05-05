"""OpenSky Network API client – multi-backend with automatic fallback.

Tries backends in this order:
  1. subprocess curl  – native TLS/JA3 fingerprint, most permissive
  2. requests         – different TLS stack than httpx, often bypasses filters
  3. httpx (HTTP/1.1) – fallback with curl-mimicking headers

Environment variables:
  OPENSKY_USERNAME / OPENSKY_PASSWORD – basic auth (increases rate limits)
  OPENSKY_FORCE_BACKEND  – force one backend: "curl" | "requests" | "httpx"
"""

import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Circuit breaker ────────────────────────────────────────────────────────────
CIRCUIT_OPEN_AFTER  = 3
CIRCUIT_RESET_AFTER = 300   # 5 minutes

_cb_failures: int   = 0
_cb_open_at:  float = 0.0


def _circuit_is_open() -> bool:
    global _cb_failures, _cb_open_at
    if _cb_failures < CIRCUIT_OPEN_AFTER:
        return False
    if time.time() - _cb_open_at >= CIRCUIT_RESET_AFTER:
        logger.info("[opensky] Circuit resetting")
        _cb_failures = 0; _cb_open_at = 0.0
        return False
    return True


def _on_fail():
    global _cb_failures, _cb_open_at
    _cb_failures += 1
    if _cb_failures == CIRCUIT_OPEN_AFTER:
        _cb_open_at = time.time()
        logger.error(
            f"[opensky] *** Circuit OPEN *** – "
            f"API unreachable after {CIRCUIT_OPEN_AFTER} failures. "
            f"Pausing {CIRCUIT_RESET_AFTER}s. "
            f"Check /stats/health/opensky for diagnosis."
        )


def _on_success():
    global _cb_failures, _cb_open_at
    if _cb_failures:
        logger.info("[opensky] Circuit closed – API reachable again")
    _cb_failures = 0; _cb_open_at = 0.0


# ── Backend implementations ────────────────────────────────────────────────────

def _curl_request(url: str, auth: Optional[tuple], timeout: int) -> Optional[Any]:
    """
    Use the system curl binary.
    curl has a different TLS/JA3 fingerprint than Python HTTP libraries.
    This is the most likely to succeed if OpenSky blocks by TLS fingerprint.
    """
    cmd = [
        "curl",
        "--silent",
        "--fail",               # exit non-zero on HTTP errors
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
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 5
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        if result.returncode == 22:    # curl --fail: HTTP error (404, etc.)
            return None
        logger.debug(f"[curl] rc={result.returncode} stderr={result.stderr[:200]}")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("[curl] subprocess timed out")
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"[curl] error: {e}")
        return None


def _requests_request(url: str, auth: Optional[tuple], timeout: int) -> Optional[Any]:
    """
    Use the requests library.
    Uses urllib3/OpenSSL under the hood – different TLS fingerprint from httpx.
    """
    try:
        import requests as req
        headers = {
            "User-Agent": "curl/7.88.1",
            "Accept":     "application/json",
        }
        r = req.get(url, headers=headers, auth=auth, timeout=timeout, verify=True)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        if r.status_code == 401:
            logger.error("[requests] 401 Unauthorised – check credentials")
            return None
        if r.status_code == 429:
            logger.warning("[requests] 429 Rate limited")
            time.sleep(60)
            return None
        logger.warning(f"[requests] HTTP {r.status_code}")
        return None
    except Exception as e:
        logger.warning(f"[requests] {type(e).__name__}: {e}")
        return None


def _httpx_request(url: str, auth: Optional[tuple], timeout: int) -> Optional[Any]:
    """
    httpx with curl-mimicking settings.
    Forces HTTP/1.1 (avoids HTTP/2 JA3 fingerprint) and curl User-Agent.
    """
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
            return r.json()
        if r.status_code == 404:
            return None
        if r.status_code == 401:
            logger.error("[httpx] 401 Unauthorised")
            return None
        logger.warning(f"[httpx] HTTP {r.status_code}")
        return None
    except Exception as e:
        logger.warning(f"[httpx] {type(e).__name__}: {e}")
        return None


# ── Client class ───────────────────────────────────────────────────────────────

class OpenSkyClient:
    """
    OpenSky Network REST API client with automatic backend selection.

    Backend priority (configurable via OPENSKY_FORCE_BACKEND):
      curl → requests → httpx

    Each backend tries once per call. If all fail, the circuit breaker
    records a failure. After CIRCUIT_OPEN_AFTER total failures the circuit
    opens and all requests are skipped for CIRCUIT_RESET_AFTER seconds.
    """

    BASE_URL = "https://opensky-network.org/api"
    TIMEOUT  = 20   # seconds per attempt (fast-fail)

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
        # Detect available backends
        self._has_curl     = self._check_curl()
        self._has_requests = self._check_requests()
        is_auth = bool(self.username and self.password)
        logger.info(
            f"[opensky] Client ready – auth={is_auth} delay={self.rate_limit_delay}s "
            f"timeout={self.TIMEOUT}s "
            f"backends: curl={'✓' if self._has_curl else '✗'} "
            f"requests={'✓' if self._has_requests else '✗'} httpx=✓"
            + (f" (forced={self._force_backend})" if self._force_backend else "")
        )

    @staticmethod
    def _check_curl() -> bool:
        try:
            subprocess.run(["curl", "--version"],
                           capture_output=True, timeout=3, check=True)
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
        Try all backends in order until one succeeds.
        Returns None if all fail (or circuit is open).
        """
        if _circuit_is_open():
            logger.debug(f"[opensky] Circuit open – skip {endpoint}")
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
            # Auto: try in order of likely success
            if self._has_curl:
                backends.append(("curl", _curl_request))
            if self._has_requests:
                backends.append(("requests", _requests_request))
            backends.append(("httpx", _httpx_request))

        for name, fn in backends:
            try:
                logger.debug(f"[opensky] {name} → {url[:80]}")
                result = fn(url, auth, self.TIMEOUT)
                if result is not None:
                    _on_success()
                    logger.debug(f"[opensky] {name} succeeded")
                    return result
                # None = 404 / no data (not a failure)
                _on_success()
                return None
            except Exception as e:
                logger.warning(f"[opensky] {name} exception: {e}")
                continue   # try next backend

        # All backends failed
        _on_fail()
        logger.error(f"[opensky] All backends failed for {endpoint}")
        return None

    @staticmethod
    def _build_url(endpoint: str, params: Dict[str, Any]) -> str:
        base = f"https://opensky-network.org/api/{endpoint}"
        if not params:
            return base
        qs = "&".join(f"{k}={v}" for k, v in params.items())
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
        logger.info(
            f"[opensky] /flights/area begin={begin} end={end} "
            f"box=({lamin},{lomin},{lamax},{lomax})"
        )
        data = self._get("flights/area", {
            "begin": begin, "end": end,
            "lamin": lamin, "lomin": lomin,
            "lamax": lamax, "lomax": lomax,
        })
        result = data if isinstance(data, list) else []
        logger.info(f"[opensky] /flights/area → {len(result)} flights")
        return result

    def get_all_flights(self, begin: int, end: int) -> List[Dict[str, Any]]:
        if end - begin > 7200:
            end = begin + 7200
        logger.info(f"[opensky] /flights/all begin={begin} end={end}")
        data = self._get("flights/all", {"begin": begin, "end": end})
        result = data if isinstance(data, list) else []
        logger.info(f"[opensky] /flights/all → {len(result)} flights")
        return result

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
        """
        Full diagnostic: test all backends and return results.
        GET /stats/health/opensky calls this.
        """
        url = self._build_url("states/all", {
            "lamin": 24, "lomin": 44, "lamax": 25, "lomax": 45
        })
        auth  = self._auth()
        results = {}

        for name, fn in [
            ("curl",     _curl_request),
            ("requests", _requests_request),
            ("httpx",    _httpx_request),
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
                data = fn(url, auth, 12)
                elapsed = round(time.time() - t0, 2)
                results[name] = {
                    "available": True,
                    "success":   data is not None,
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
            "circuit_open":         _circuit_is_open(),
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
        return _circuit_is_open()

    @property
    def consecutive_failures(self) -> int:
        return _cb_failures