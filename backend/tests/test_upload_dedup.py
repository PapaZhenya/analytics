import io
import uuid

import pytest
from fastapi import UploadFile

from backend.tests.conftest import requires_postgres


def _make_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename)


@requires_postgres
def test_duplicate_checksum_upload_is_rejected(db_session, seed_reference_data, tmp_path, monkeypatch):
    from backend.app.models.org import Project, User
    from backend.app.services.call_service import DuplicateUploadError, create_call_from_upload
    from backend.app.services import call_service
    from backend.pipeline.storage import LocalFilesystemStorage

    monkeypatch.setattr(
        call_service, "get_storage", lambda: LocalFilesystemStorage(str(tmp_path))
    )

    org = seed_reference_data["org"]
    project = Project(id=uuid.uuid4(), org_id=org.id, name="Test Project")
    user = User(
        id=uuid.uuid4(), org_id=org.id, email="uploader@example.com",
        password_hash="x", full_name="Uploader", role_id=seed_reference_data["roles"]["admin"].id,
    )
    db_session.add_all([project, user])
    db_session.commit()

    content = b"identical-audio-bytes"

    first_call = create_call_from_upload(
        db_session, user, project.id, None, _make_upload("call1.mp3", content)
    )
    assert first_call.checksum is not None

    with pytest.raises(DuplicateUploadError) as exc_info:
        create_call_from_upload(
            db_session, user, project.id, None, _make_upload("call1_again.mp3", content)
        )
    assert exc_info.value.existing_call.id == first_call.id


@requires_postgres
def test_unsupported_file_extension_is_rejected(db_session, seed_reference_data, tmp_path, monkeypatch):
    from backend.app.models.org import Project, User
    from backend.app.services.call_service import UnsupportedFileTypeError, create_call_from_upload
    from backend.app.services import call_service
    from backend.pipeline.storage import LocalFilesystemStorage

    monkeypatch.setattr(
        call_service, "get_storage", lambda: LocalFilesystemStorage(str(tmp_path))
    )

    org = seed_reference_data["org"]
    project = Project(id=uuid.uuid4(), org_id=org.id, name="Test Project 2")
    user = User(
        id=uuid.uuid4(), org_id=org.id, email="uploader2@example.com",
        password_hash="x", full_name="Uploader2", role_id=seed_reference_data["roles"]["admin"].id,
    )
    db_session.add_all([project, user])
    db_session.commit()

    with pytest.raises(UnsupportedFileTypeError):
        create_call_from_upload(
            db_session, user, project.id, None, _make_upload("malware.exe", b"not audio")
        )
