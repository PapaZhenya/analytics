"""refresh_tokens table (rotation/revocation support)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE refresh_tokens (
            user_id UUID NOT NULL,
            jti UUID NOT NULL,
            issued_at TIMESTAMP WITH TIME ZONE NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            revoked_at TIMESTAMP WITH TIME ZONE,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX ix_refresh_tokens_jti ON refresh_tokens (jti)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refresh_tokens CASCADE")
