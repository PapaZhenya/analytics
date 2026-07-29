"""audio pipeline requirements: channel metadata, model version tracking, role confidence

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29

Adds the fields needed to honestly expose uncertainty (role_confidence), track which
model versions processed a call (model_versions), and record channel-layout metadata
(channel_count / is_separate_channel_recording) so the pipeline can eventually treat
separate-channel telephony recordings differently from single-track ones. None of this
retroactively touches existing rows differently than NULL/default — see downgrade for
the exact reverse.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE calls ADD COLUMN channel_count INTEGER")
    op.execute("ALTER TABLE calls ADD COLUMN is_separate_channel_recording BOOLEAN")
    op.execute("ALTER TABLE calls ADD COLUMN model_versions JSONB NOT NULL DEFAULT '{}'::jsonb")

    op.execute("ALTER TABLE speakers ADD COLUMN role_confidence NUMERIC")
    op.execute("ALTER TABLE speakers ADD COLUMN role_corrected_by UUID REFERENCES users (id)")
    op.execute("ALTER TABLE speakers ADD COLUMN role_corrected_at TIMESTAMP WITH TIME ZONE")


def downgrade() -> None:
    op.execute("ALTER TABLE speakers DROP COLUMN IF EXISTS role_corrected_at")
    op.execute("ALTER TABLE speakers DROP COLUMN IF EXISTS role_corrected_by")
    op.execute("ALTER TABLE speakers DROP COLUMN IF EXISTS role_confidence")

    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS model_versions")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS is_separate_channel_recording")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS channel_count")
