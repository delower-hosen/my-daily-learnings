from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api import health, sessions
from app.core.config import settings
from app.core.database import create_tables
from app.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    create_tables()
    yield


app = FastAPI(
    title="Buro Liveness Engine",
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Normalize HTTPException so all errors use {"error": ...} envelope
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        content = detail  # already our envelope
    else:
        content = {"error": {"code": "HTTP_ERROR", "message": str(detail)}}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import traceback, logging
    logging.getLogger("app").error("Unhandled exception: %s", traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
    )
