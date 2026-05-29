"""review_stages 심각도 집계 컬럼 추가

Revision ID: a4f2c7e9d8b1
Revises: 9c1a2b3d4e5f
Create Date: 2026-05-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4f2c7e9d8b1"
down_revision: Union[str, Sequence[str], None] = "9c1a2b3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name in (
        "severity_l0_count",
        "severity_l1_count",
        "severity_l2_count",
        "severity_l3_count",
        "severity_l4_count",
    ):
        op.add_column(
            "review_stages",
            sa.Column(name, sa.Integer(), server_default="0", nullable=False),
        )


def downgrade() -> None:
    for name in (
        "severity_l4_count",
        "severity_l3_count",
        "severity_l2_count",
        "severity_l1_count",
        "severity_l0_count",
    ):
        op.drop_column("review_stages", name)
