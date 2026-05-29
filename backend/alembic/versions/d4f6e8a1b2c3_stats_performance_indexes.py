"""통계 조회 성능 보조 인덱스 추가

Revision ID: d4f6e8a1b2c3
Revises: c8d1e2f3a4b5
Create Date: 2026-05-30 00:00:00.000000

Supabase slow query 리포트에서 반복 호출이 확인된 배정자/단계 필터를
복합 인덱스로 보조한다.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d4f6e8a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c8d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_buildings_assigned_reviewer_name_current_phase",
        "buildings",
        ["assigned_reviewer_name", "current_phase"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_buildings_assigned_reviewer_name_current_phase",
        table_name="buildings",
    )
