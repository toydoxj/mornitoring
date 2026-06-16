"""buildings에 준다중이용 여부 컬럼 추가

Revision ID: b3c4d5e6f7a8
Revises: 5f2c8a1d9e70
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "5f2c8a1d9e70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("buildings", sa.Column("is_quasi_multi_use", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("buildings", "is_quasi_multi_use")
