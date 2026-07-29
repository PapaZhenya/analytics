import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import redis

from backend.app.config import get_settings
from backend.app.db.session import SessionLocal
from backend.app.models.calls import Call, CallStatus
from backend.app.models.calls import ProcessingJob
from backend.tasks.celery_app import celery_app

settings = get_settings()
_redis_client = redis.Redis.from_url(settings.redis_url)

_LOCK_TTL_SECONDS = 6 * 3600  # generous — a full pipeline run can legitimately take a while


@contextmanager
def _call_lock(call_id: str):
    """Prevents two workers from processing the same call concurrently (e.g. a retried
    task overlapping with the original delivery)."""
    lock_key = f"call_lock:{call_id}"
    acquired = _redis_client.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
    try:
        yield acquired
    finally:
        if acquired:
            _redis_client.delete(lock_key)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, acks_late=True)
def process_call(self, call_id: str) -> None:
    from backend.pipeline.orchestrator import run_pipeline  # local import: heavy ML deps

    with _call_lock(call_id) as acquired:
        if not acquired:
            # Another worker already holds this call — do not reprocess/duplicate.
            return

        db = SessionLocal()
        try:
            job = ProcessingJob(
                id=uuid.uuid4(),
                call_id=uuid.UUID(call_id),
                celery_task_id=self.request.id or "unknown",
                attempt=self.request.retries + 1,
                status="running",
            )
            db.add(job)
            db.commit()
        finally:
            db.close()

        try:
            asyncio.run(run_pipeline(call_id))
        except Exception as exc:  # noqa: BLE001 — must record failure before deciding retry
            db = SessionLocal()
            try:
                call = db.get(Call, uuid.UUID(call_id))
                job = (
                    db.query(ProcessingJob)
                    .filter(ProcessingJob.call_id == uuid.UUID(call_id))
                    .order_by(ProcessingJob.created_at.desc())
                    .first()
                )
                if job is not None:
                    job.status = "failed"
                    job.last_error = str(exc)
                if call is not None and self.request.retries >= self.max_retries:
                    call.status = CallStatus.failed
                    call.processed_at = datetime.now(timezone.utc)
                db.commit()
            finally:
                db.close()

            raise self.retry(exc=exc)
        else:
            db = SessionLocal()
            try:
                job = (
                    db.query(ProcessingJob)
                    .filter(ProcessingJob.call_id == uuid.UUID(call_id))
                    .order_by(ProcessingJob.created_at.desc())
                    .first()
                )
                if job is not None:
                    job.status = "succeeded"
                db.commit()
            finally:
                db.close()
