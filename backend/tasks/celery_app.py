from celery import Celery

from backend.app.config import get_settings
from backend.app.logging_config import configure_logging

settings = get_settings()

celery_app = Celery(
    "callytics",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=["backend.tasks.process_call"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_default_queue=settings.celery_gpu_queue,
    task_track_started=True,
    # Celery hijacks the root logger by default (its own setup_logging signal handler)
    # — disabled so configure_logging()'s JSON formatter below is what actually ends up
    # emitting worker log lines, same structured format as the api process.
    worker_hijack_root_logger=False,
)

configure_logging(settings.log_level)
