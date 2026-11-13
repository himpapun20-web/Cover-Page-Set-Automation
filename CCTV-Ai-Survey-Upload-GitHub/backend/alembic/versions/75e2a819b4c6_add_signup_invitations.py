"""add signup invitations

Revision ID: 75e2a819b4c6
Revises: 0f9f8b2a1c43
Create Date: 2026-11-07 11:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "75e2a819b4c6"
down_revision: Union[str, None] = "0f9f8b2a1c43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signup_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_signup_invitations_company_id", "signup_invitations", ["company_id"])
    op.create_index("ix_signup_invitations_expires_at", "signup_invitations", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_signup_invitations_expires_at", table_name="signup_invitations")
    op.drop_index("ix_signup_invitations_company_id", table_name="signup_invitations")
    op.drop_table("signup_invitations")
