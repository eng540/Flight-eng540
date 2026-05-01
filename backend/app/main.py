"""Main FastAPI application – Flight Intelligence v2."""
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging, time, os, mimetypes

mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('image/svg+xml', '.svg')

from app.config import settings
from app.api import flights, stats, airlines, analytics, ingestion, regions
from app.api import live, history, system as system_api
from app.api import operations as operations_api

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} v2")
    yield
    logger.info(f"Shutting down {settings.APP_NAME}")


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    response.headers["X-Process-Time"] = str(time.time() - start)
    return response


# ── API Routers ───────────────────────────────────────────────────────────────
# v1 routers (new — /api/v1/* prefix)
app.include_router(operations_api.router)  # /api/v1/operations/*
app.include_router(live.router)                # GET /api/v1/live/positions
app.include_router(flights.router)             # GET /api/v1/flights/...
app.include_router(flights.aircraft_router)    # GET /api/v1/aircraft/{icao24}/history
app.include_router(analytics.router)           # GET /api/v1/analytics/...
app.include_router(history.router)             # POST /api/v1/history/query
app.include_router(system_api.router)          # GET /api/v1/system/credits-usage
app.include_router(ingestion.router_v1)        # GET /api/v1/ingestion/jobs

# Legacy routers (no /api/v1/ prefix — kept for frontend backward compat)
app.include_router(flights.legacy_router)      # GET /flights (legacy map)
app.include_router(stats.router)               # GET /stats
app.include_router(airlines.router)            # GET /airlines
app.include_router(analytics.legacy_router)    # GET /analytics/...
app.include_router(ingestion.router)           # GET /ingestion/jobs
app.include_router(regions.router)             # GET /regions


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "2.0.0"}


# ── Serve React frontend ──────────────────────────────────────────────────────
# In production the frontend is built into /app/frontend/dist (see Dockerfile)
frontend_dist = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../frontend/dist"))

if os.path.exists(frontend_dist):
    logger.info(f"Serving frontend from: {frontend_dist}")
    assets_path = os.path.join(frontend_dist, "assets")
    if os.path.exists(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

    @app.get("/{file_name}.{ext}")
    async def serve_root_files(file_name: str, ext: str):
        p = os.path.join(frontend_dist, f"{file_name}.{ext}")
        if os.path.isfile(p):
            return FileResponse(p)
        raise HTTPException(status_code=404, detail="Not found")

    @app.get("/{catchall:path}")
    async def serve_react_app(catchall: str):
        idx = os.path.join(frontend_dist, "index.html")
        if os.path.exists(idx):
            return FileResponse(idx)
        raise HTTPException(status_code=404, detail="index.html not found")
else:
    logger.warning("Frontend build not found – API-only mode")

    @app.get("/")
    async def root():
        return {"message": "Flight Intelligence API v2 is running", "docs": "/docs"}
