"""seed reference data: roles, permissions, speaker_roles, default org/project

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-28

Deliberately does NOT create a default admin user with a fixed password (a known
default-credential pair is a real vulnerability). Bootstrap the first Super Admin with
backend/scripts/create_superuser.py after running migrations.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = [
    ("super_admin", "Super Admin"),
    ("admin", "Admin"),
    ("qa_reviewer", "QA Reviewer"),
    ("manager", "Manager"),
    ("team_leader", "Team Leader"),
    ("viewer", "Viewer"),
]

PERMISSIONS = [
    ("calls.upload", "Upload call recordings"),
    ("calls.view", "View calls and transcripts"),
    ("calls.reprocess", "Reprocess a call through the pipeline"),
    ("calls.cancel", "Cancel a queued/processing call"),
    ("calls.review", "Confirm/reject/correct QA findings, add/remove evidence"),
    ("transcripts.correct", "Correct transcript text or speaker assignment"),
    ("comments.create", "Add comments on a call"),
    ("scorecards.view", "View scorecard definitions"),
]

ROLE_PERMISSIONS = {
    "super_admin": [p[0] for p in PERMISSIONS],
    "admin": [p[0] for p in PERMISSIONS],
    "qa_reviewer": [
        "calls.upload", "calls.view", "calls.review", "transcripts.correct",
        "comments.create", "scorecards.view",
    ],
    "manager": ["calls.view", "calls.reprocess", "calls.cancel", "comments.create", "scorecards.view"],
    "team_leader": ["calls.view", "comments.create", "scorecards.view"],
    "viewer": ["calls.view", "scorecards.view"],
}

SPEAKER_ROLES = [
    ("agent", "Agent"),
    ("client", "Client"),
    ("other", "Other"),
    ("unknown", "Unknown"),
]

DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def upgrade() -> None:
    conn = op.get_bind()

    role_ids = {}
    for code, label in ROLES:
        role_id = uuid.uuid4()
        role_ids[code] = role_id
        conn.execute(
            sa.text("INSERT INTO roles (id, code, label) VALUES (:id, :code, :label)"),
            {"id": role_id, "code": code, "label": label},
        )

    permission_ids = {}
    for code, label in PERMISSIONS:
        perm_id = uuid.uuid4()
        permission_ids[code] = perm_id
        conn.execute(
            sa.text("INSERT INTO permissions (id, code, label) VALUES (:id, :code, :label)"),
            {"id": perm_id, "code": code, "label": label},
        )

    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        for perm_code in perm_codes:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (id, role_id, permission_id) "
                    "VALUES (:id, :role_id, :permission_id)"
                ),
                {
                    "id": uuid.uuid4(),
                    "role_id": role_ids[role_code],
                    "permission_id": permission_ids[perm_code],
                },
            )

    for code, label in SPEAKER_ROLES:
        conn.execute(
            sa.text("INSERT INTO speaker_roles (id, code, label) VALUES (:id, :code, :label)"),
            {"id": uuid.uuid4(), "code": code, "label": label},
        )

    conn.execute(
        sa.text(
            "INSERT INTO organizations (id, name, created_at, updated_at) "
            "VALUES (:id, :name, now(), now())"
        ),
        {"id": DEFAULT_ORG_ID, "name": "Default Organization"},
    )
    conn.execute(
        sa.text(
            "INSERT INTO projects (id, org_id, name, description, created_at, updated_at) "
            "VALUES (:id, :org_id, :name, :description, now(), now())"
        ),
        {
            "id": DEFAULT_PROJECT_ID,
            "org_id": DEFAULT_ORG_ID,
            "name": "Default Project",
            "description": "Seeded Phase 1 project — rename or add more via the admin console (Phase 2).",
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM projects WHERE id = :id"), {"id": DEFAULT_PROJECT_ID})
    conn.execute(sa.text("DELETE FROM organizations WHERE id = :id"), {"id": DEFAULT_ORG_ID})
    conn.execute(sa.text("DELETE FROM speaker_roles"))
    conn.execute(sa.text("DELETE FROM role_permissions"))
    conn.execute(sa.text("DELETE FROM permissions"))
    conn.execute(sa.text("DELETE FROM roles"))
