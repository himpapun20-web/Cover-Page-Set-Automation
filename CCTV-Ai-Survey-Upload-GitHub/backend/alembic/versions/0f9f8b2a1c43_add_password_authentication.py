"""add password authentication

Revision ID: 0f9f8b2a1c43
Revises: f3819c2a4d10
Create Date: 2026-11-04 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0f9f8b2a1c43"
down_revision: Union[str, None] = "f3819c2a4d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
