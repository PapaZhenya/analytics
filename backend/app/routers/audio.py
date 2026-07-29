"""Audio streaming — split out from calls.py: this is a storage-serving concern
(range-request handling over AudioStorage), distinct from call-lifecycle CRUD."""
import uuid

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.dependencies import get_call_or_404, require_permission
from backend.app.models.org import User
from backend.pipeline.storage import get_storage

router = APIRouter(prefix="/calls", tags=["audio"])


@router.get("/{call_id}/audio")
def stream_audio(
    call_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("calls.view")),
    db: Session = Depends(get_db),
):
    call = get_call_or_404(db, call_id)
    storage = get_storage()
    file_size = storage.size(call.storage_path)

    range_header = request.headers.get("range")
    start, end = 0, file_size - 1
    status_code = status.HTTP_200_OK
    if range_header:
        try:
            range_value = range_header.replace("bytes=", "").split("-")
            start = int(range_value[0]) if range_value[0] else 0
            end = int(range_value[1]) if len(range_value) > 1 and range_value[1] else file_size - 1
            status_code = status.HTTP_206_PARTIAL_CONTENT
        except ValueError:
            pass

    content_length = end - start + 1
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
    }
    ext = call.original_filename.rsplit(".", 1)[-1].lower()
    media_type = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac"}.get(ext, "application/octet-stream")

    return StreamingResponse(
        storage.stream(call.storage_path, start=start, end=end + 1),
        status_code=status_code,
        headers=headers,
        media_type=media_type,
    )
