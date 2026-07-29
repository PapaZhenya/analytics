import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.app.config import get_settings
from backend.app.logging_config import configure_logging
from backend.app.rate_limit import limiter
from backend.app.routers import (
    audio,
    auth,
    calls,
    comments,
    findings,
    health,
    projects,
    scorecards,
    teams,
    transcripts,
)

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("backend.app.access")


def create_app() -> FastAPI:
    app = FastAPI(title="Call-Center QA Analytics Platform API", version="0.1.0")

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request",
            extra={
                "http_method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(calls.router, prefix="/api/v1")
    app.include_router(audio.router, prefix="/api/v1")
    app.include_router(transcripts.router, prefix="/api/v1")
    app.include_router(findings.router, prefix="/api/v1")
    app.include_router(comments.router, prefix="/api/v1")
    app.include_router(scorecards.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(teams.router, prefix="/api/v1")

    return app


app = create_app()
