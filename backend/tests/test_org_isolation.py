"""Section 9 requires 'tenant or organization isolation if multi-tenancy is enabled'.
Multi-tenancy isn't enabled (single-org deployment, confirmed in the approved plan),
but every Call/Finding-reachable row already carries org_id, and a user from one org
must never be able to reach another org's call by guessing/enumerating its UUID —
that's real defense-in-depth, not a hypothetical concern gated on a feature flag."""
import uuid
from datetime import datetime, timezone

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
def test_user_cannot_access_another_orgs_call(db_session, seed_reference_data):
    from backend.app.models.calls import Call, CallSource, CallStatus
    from backend.app.models.org import Organization, Project, User
    from backend.app.security import hash_password

    org_a = seed_reference_data["org"]
    org_b = Organization(id=uuid.uuid4(), name="Other Org")
    db_session.add(org_b)
    db_session.commit()

    project_a = Project(id=uuid.uuid4(), org_id=org_a.id, name="Org A Project")
    project_b = Project(id=uuid.uuid4(), org_id=org_b.id, name="Org B Project")
    user_a = User(
        id=uuid.uuid4(), org_id=org_a.id, email="orga@example.com",
        password_hash=hash_password("s3cret!"), full_name="User A",
        role_id=seed_reference_data["roles"]["admin"].id,
    )
    user_b = User(
        id=uuid.uuid4(), org_id=org_b.id, email="orgb@example.com",
        password_hash=hash_password("s3cret!"), full_name="User B",
        role_id=seed_reference_data["roles"]["admin"].id,
    )
    db_session.add_all([project_a, project_b, user_a, user_b])
    db_session.commit()

    call_b = Call(
        id=uuid.uuid4(), org_id=org_b.id, project_id=project_b.id, uploaded_by=user_b.id,
        source=CallSource.upload, original_filename="orgb-call.mp3", storage_path="x.mp3",
        checksum="d" * 64, status=CallStatus.completed, uploaded_at=datetime.now(timezone.utc),
    )
    db_session.add(call_b)
    db_session.commit()

    client = _make_client(db_session)
    login = client.post("/api/v1/auth/login", json={"email": "orga@example.com", "password": "s3cret!"})
    token_a = login.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # User A (org A) must not be able to fetch Org B's call by guessing its UUID.
    response = client.get(f"/api/v1/calls/{call_b.id}", headers=headers_a)
    assert response.status_code == 404

    # Same for the audio-streaming and utterance-correction-history endpoints.
    assert client.get(f"/api/v1/calls/{call_b.id}/audio", headers=headers_a).status_code == 404
    assert client.get(f"/api/v1/calls/{call_b.id}/status", headers=headers_a).status_code == 404

    # But Org B's own user can see it fine — this isn't a general permissions bug,
    # it's specifically an org-boundary check.
    login_b = client.post("/api/v1/auth/login", json={"email": "orgb@example.com", "password": "s3cret!"})
    token_b = login_b.json()["access_token"]
    response_b = client.get(f"/api/v1/calls/{call_b.id}", headers={"Authorization": f"Bearer {token_b}"})
    assert response_b.status_code == 200
