from celery import Celery

from backend.app.config import get_settings

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
)
