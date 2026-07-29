from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.app.config import get_settings
from backend.app.rate_limit import limiter
from backend.app.routers import auth, calls, comments, findings, health, projects, scorecards, teams

settings = get_settings()


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

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(calls.router, prefix="/api/v1")
    app.include_router(findings.router, prefix="/api/v1")
    app.include_router(comments.router, prefix="/api/v1")
    app.include_router(scorecards.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(teams.router, prefix="/api/v1")

    return app


app = create_app()
