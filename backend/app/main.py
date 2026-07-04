from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.alerts import router as alerts_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.integrations import router as integrations_router
from app.api.watches import router as watches_router
from app.core.db import ensure_indexes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    yield


app = FastAPI(title="FareWatch", version="0.1.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "error", "detail": str(exc.detail)},
    )


app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(watches_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
