import uuid
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.calls import Call, CallSource, CallStatus
from backend.app.models.org import User
from backend.pipeline.storage import get_storage, sha256_of

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}


class DuplicateUploadError(Exception):
    def __init__(self, existing_call: Call):
        self.existing_call = existing_call
        super().__init__(f"Duplicate upload of an existing call: {existing_call.id}")


class UnsupportedFileTypeError(Exception):
    pass


def _extension_of(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""


def create_call_from_upload(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    upload: UploadFile,
) -> Call:
    ext = _extension_of(upload.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    checksum = sha256_of(upload.file)

    existing = db.execute(
        select(Call).where(Call.project_id == project_id, Call.checksum == checksum)
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateUploadError(existing)

    call_id = uuid.uuid4()
    storage = get_storage()
    storage_path = storage.save(str(call_id), upload.filename or f"{call_id}{ext}", upload.file)
    file_size = storage.size(storage_path)

    call = Call(
        id=call_id,
        org_id=user.org_id,
        project_id=project_id,
        agent_id=agent_id,
        uploaded_by=user.id,
        source=CallSource.upload,
        original_filename=upload.filename or str(call_id),
        storage_path=storage_path,
        checksum=checksum,
        file_size_bytes=file_size,
        status=CallStatus.queued,
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    _enqueue_processing(call.id)
    return call


def _enqueue_processing(call_id: uuid.UUID) -> None:
    from backend.tasks.process_call import process_call

    process_call.delay(str(call_id))


def reprocess_call(db: Session, call: Call) -> None:
    """Re-enqueues processing. Existing call_processing_steps rows are left in place —
    the orchestrator's resumability logic will skip any already-succeeded steps and only
    redo what's needed (e.g. everything, if the caller wants a full redo they should
    reset the steps first; Phase 1 keeps this simple: reprocess resumes, it does not
    force a clean rebuild)."""
    call.status = CallStatus.queued
    db.commit()
    _enqueue_processing(call.id)


def cancel_call(db: Session, call: Call) -> bool:
    """Cooperative cancellation: only safe while nothing is actively running yet."""
    if call.status not in (CallStatus.uploaded, CallStatus.queued):
        return False
    call.status = CallStatus.cancelled
    db.commit()
    return True
