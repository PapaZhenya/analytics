import uuid

import pytest
from fastapi.testclient import TestClient

from backend.tests.conftest import requires_postgres


def _make_client(db_session_override) -> TestClient:
    from backend.app.db.session import get_db
    from backend.app.main import app

    def _override():
        yield db_session_override

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


@requires_postgres
def test_login_rejects_unknown_user(db_session, seed_reference_data):
    client = _make_client(db_session)
    response = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert response.status_code == 401


@requires_postgres
def test_login_and_me_roundtrip(db_session, seed_reference_data):
    from backend.app.models.org import User
    from backend.app.security import hash_password

    org = seed_reference_data["org"]
    role = seed_reference_data["roles"]["qa_reviewer"]
    user = User(
        id=uuid.uuid4(), org_id=org.id, email="reviewer@example.com",
        password_hash=hash_password("s3cret!"), full_name="Test Reviewer", role_id=role.id,
    )
    db_session.add(user)
    db_session.commit()

    client = _make_client(db_session)

    login_response = client.post(
        "/api/v1/auth/login", json={"email": "reviewer@example.com", "password": "s3cret!"}
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]

    me_response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "reviewer@example.com"
    assert me_response.json()["role_code"] == "qa_reviewer"


@requires_postgres
def test_viewer_role_cannot_upload_calls(db_session, seed_reference_data):
    """RBAC must be enforced server-side: a Viewer (read-only role) hitting the upload
    endpoint must get 403, regardless of what the frontend would or wouldn't show them."""
    from backend.app.models.org import User
    from backend.app.security import hash_password

    org = seed_reference_data["org"]
    viewer_role = seed_reference_data["roles"]["viewer"]
    user = User(
        id=uuid.uuid4(), org_id=org.id, email="viewer@example.com",
        password_hash=hash_password("s3cret!"), full_name="Test Viewer", role_id=viewer_role.id,
    )
    db_session.add(user)
    db_session.commit()

    client = _make_client(db_session)
    login_response = client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.com", "password": "s3cret!"}
    )
    access_token = login_response.json()["access_token"]

    response = client.post(
        "/api/v1/calls",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"project_id": str(uuid.uuid4())},
        files={"files": ("test.mp3", b"fake-audio-bytes", "audio/mpeg")},
    )
    assert response.status_code == 403


@requires_postgres
def test_failed_login_for_existing_user_is_audit_logged(db_session, seed_reference_data):
    """Section 9 requires audit logging; failed logins matter most for detecting
    brute-force/credential-stuffing attempts, not just successful ones."""
    from backend.app.models.org import AuditLog, User
    from backend.app.security import hash_password

    org = seed_reference_data["org"]
    role = seed_reference_data["roles"]["qa_reviewer"]
    user = User(
        id=uuid.uuid4(), org_id=org.id, email="audit-target@example.com",
        password_hash=hash_password("correct-password"), full_name="Audit Target", role_id=role.id,
    )
    db_session.add(user)
    db_session.commit()

    client = _make_client(db_session)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "audit-target@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401

    entries = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "login_failed", AuditLog.user_id == user.id)
        .all()
    )
    assert len(entries) == 1
