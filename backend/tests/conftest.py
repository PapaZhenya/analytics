"""DB-backed fixtures require a real PostgreSQL instance (native UUID/JSONB/ENUM types
used throughout backend/app/models are Postgres-specific — SQLite can't stand in for
them). Point TEST_DATABASE_URL at a disposable Postgres database (the docker-compose
stack's `postgres` service, or a local one) to run the DB-dependent tests; without it,
those tests are skipped rather than failing, so `pytest` still runs cleanly in
environments without Postgres available (e.g. a plain dev container).
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# JWT_SECRET_KEY has no default in Settings (backend/app/config.py) — deliberately, so
# a real deployment fails to start rather than silently signing tokens with a hardcoded
# fallback. Tests need *some* value; this one is only ever used inside this test
# process and is never a real deployment's secret.
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-never-used-outside-pytest")

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

requires_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set TEST_DATABASE_URL to a disposable Postgres DB to run this test.",
)


@pytest.fixture(scope="session")
def engine():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    from backend.app.models import Base

    eng = create_engine(TEST_DATABASE_URL, future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def seed_reference_data(db_session):
    """Mirrors alembic/versions/0002_seed_reference_data.py's inserts, so tests don't
    depend on migrations having been run against the test DB."""
    from backend.app.models.calls import SpeakerRole
    from backend.app.models.org import Organization, Permission, Role, RolePermission

    roles = {}
    for code, label in [
        ("super_admin", "Super Admin"), ("admin", "Admin"), ("qa_reviewer", "QA Reviewer"),
        ("manager", "Manager"), ("team_leader", "Team Leader"), ("viewer", "Viewer"),
    ]:
        role = Role(id=uuid.uuid4(), code=code, label=label)
        db_session.add(role)
        roles[code] = role
    db_session.flush()

    permissions = {}
    for code, label in [
        ("calls.upload", "x"), ("calls.view", "x"), ("calls.reprocess", "x"),
        ("calls.cancel", "x"), ("calls.review", "x"), ("transcripts.correct", "x"),
        ("comments.create", "x"), ("scorecards.view", "x"),
    ]:
        perm = Permission(id=uuid.uuid4(), code=code, label=label)
        db_session.add(perm)
        permissions[code] = perm
    db_session.flush()

    for perm in permissions.values():
        db_session.add(
            RolePermission(id=uuid.uuid4(), role_id=roles["admin"].id, permission_id=perm.id)
        )
    for code in ["calls.upload", "calls.view", "calls.review", "transcripts.correct", "comments.create", "scorecards.view"]:
        db_session.add(
            RolePermission(id=uuid.uuid4(), role_id=roles["qa_reviewer"].id, permission_id=permissions[code].id)
        )
    for code in ["calls.view", "scorecards.view"]:
        db_session.add(
            RolePermission(id=uuid.uuid4(), role_id=roles["viewer"].id, permission_id=permissions[code].id)
        )

    for code, label in [("agent", "Agent"), ("client", "Client"), ("other", "Other"), ("unknown", "Unknown")]:
        db_session.add(SpeakerRole(id=uuid.uuid4(), code=code, label=label))

    org = Organization(id=uuid.uuid4(), name="Test Org")
    db_session.add(org)
    db_session.flush()
    db_session.commit()

    return {"roles": roles, "permissions": permissions, "org": org}
