"""add WinCan pipe defect and environment summaries

Revision ID: b12a9cd78ef0
Revises: 75e2a819b4c6
Create Date: 2026-11-11 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b12a9cd78ef0"
down_revision: Union[str, None] = "75e2a819b4c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipe_sections", sa.Column("defects_summary", sa.Text(), nullable=True))
    op.add_column("pipe_sections", sa.Column("site_environment", sa.Text(), nullable=True))
    op.add_column("pipe_sections", sa.Column("wincan_report_imported", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("pipe_sections", "wincan_report_imported")
    op.drop_column("pipe_sections", "site_environment")
    op.drop_column("pipe_sections", "defects_summary")
