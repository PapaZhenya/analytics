from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://callytics:callytics@localhost:5432/callytics"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_gpu_queue: str = "pipeline_gpu"
    # Long calls are an explicit design requirement (section 5 of the product spec) —
    # these bound worst-case processing time so a pathologically long/corrupt-but-not-
    # rejected recording can't hang a GPU worker indefinitely. Generous defaults (2h
    # hard / 1h50m soft) since a real multi-hour call plus a large local LLM can
    # legitimately take a while; tune per deployment.
    pipeline_task_soft_time_limit_seconds: int = 60 * 110
    pipeline_task_time_limit_seconds: int = 60 * 120

    # Auth
    # No default on purpose: a hardcoded fallback secret is a well-known vulnerability
    # class (an app that silently starts and signs real JWTs with a secret published in
    # its own source code) — this must come from the environment, and pydantic-settings
    # will raise a clear startup error if JWT_SECRET_KEY isn't set, rather than the app
    # quietly running insecurely. Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(64))"
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 20
    refresh_token_expire_days: int = 14

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]

    # Storage
    storage_backend: str = "local"  # "local" (dev default) | "s3" (production option)
    storage_local_path: str = "./.data/audio"
    storage_s3_bucket: str | None = None
    storage_s3_endpoint_url: str | None = None  # set for MinIO/other S3-compatible; leave unset for real AWS S3
    storage_s3_region: str = "us-east-1"
    # Enforced two ways: an early Content-Length check (app/main.py's
    # reject_oversized_uploads middleware, rejects an honest oversized request before
    # the body is even read) and a post-save size check (call_service.py, catches a
    # missing/wrong Content-Length). Neither stops a client that lies about
    # Content-Length and streams more than it declared — that needs a reverse-proxy-
    # level limit (e.g. nginx client_max_body_size). The docker-compose.yml in this repo
    # exposes the api service directly with no reverse proxy in front of it, so that
    # outer layer does NOT currently exist here — add one (frontend/nginx.conf's nginx
    # only serves the SPA today, it doesn't proxy /api) before relying on this app-level
    # check as the sole defense in a hostile-network production deployment.
    max_upload_size_bytes: int = 500 * 1024 * 1024  # 500 MB — generous for a call recording

    # Retention: Call.retention_expires_at is set at upload time to uploaded_at + this
    # many days. backend/scripts/purge_expired_calls.py is the (manually/cron-invoked)
    # enforcement — see that script's docstring for why this isn't yet an automatic
    # Celery Beat schedule. None disables retention entirely (calls are never flagged
    # for deletion) — that is the current default, since a data-retention *duration* is
    # a business/compliance decision this platform can't default on its own behalf.
    default_retention_days: int | None = None

    # Pipeline config paths (existing repo)
    pipeline_config_path: str = "config/config.yaml"
    pipeline_prompt_path: str = "config/prompt.yaml"
    pipeline_nemo_config_path: str = "config/nemo/diar_infer_telephonic.yaml"
    pipeline_temp_dir: str = ".temp"

    # LLM provider selection (src/text/model.py::ModelRegistry model_id: "llama" |
    # "openai" | "azure_openai"). Defaults to "llama" — a locally-run HuggingFace model
    # (config/config.yaml's models.llama.model_name) — so the default production mode
    # never silently depends on an external AI API. Set LLM_PROVIDER=openai explicitly
    # to opt into OpenAI; nothing in this codebase selects it on its own.
    llm_provider: str = "llama"

    # Rate limiting
    login_rate_limit: str = "10/minute"

    # Logging
    log_level: str = "INFO"

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
