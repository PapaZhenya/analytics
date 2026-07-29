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
    jwt_secret_key: str = "change-me-in-.env"
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
