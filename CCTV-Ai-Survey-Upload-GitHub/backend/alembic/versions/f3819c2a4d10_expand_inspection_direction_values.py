"""expand supported inspection directions for filename imports

Revision ID: f3819c2a4d10
Revises: 42ec2cff90cf
Create Date: 2026-11-03 02:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3819c2a4d10"
down_revision: Union[str, None] = "42ec2cff90cf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("inspections", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_inspections_direction", type_="check")
    op.execute(sa.text("""
        UPDATE inspections
        SET inspection_direction = CASE UPPER(inspection_direction)
            WHEN 'FORWARD' THEN 'DOWNSTREAM'
            WHEN 'REVERSE' THEN 'UPSTREAM'
            ELSE UPPER(inspection_direction)
        END
    """))
    with op.batch_alter_table("inspections", recreate="always") as batch_op:
        batch_op.create_check_constraint(
            "ck_inspections_direction",
            "inspection_direction IN ('FORWARD','REVERSE','UPSTREAM','DOWNSTREAM')",
        )


def downgrade() -> None:
    with op.batch_alter_table("inspections", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_inspections_direction", type_="check")
    op.execute(sa.text("""
        UPDATE inspections
        SET inspection_direction = CASE UPPER(inspection_direction)
            WHEN 'DOWNSTREAM' THEN 'FORWARD'
            WHEN 'UPSTREAM' THEN 'REVERSE'
            ELSE UPPER(inspection_direction)
        END
    """))
    with op.batch_alter_table("inspections", recreate="always") as batch_op:
        batch_op.create_check_constraint(
            "ck_inspections_direction",
            "inspection_direction IN ('FORWARD','REVERSE')",
        )
