"""대시보드 성능: 조회 빈발 컬럼 인덱스 추가

Revision ID: c47b3f51ab90
Revises: b1a7c3d49012
Create Date: 2026-04-18 00:00:00.000000

대시보드 `/api/buildings/stats` 와 `/api/buildings/my-stats` 가 GROUP BY /
필터에 사용하는 `buildings.current_phase`, `buildings.final_result`,
`review_stages.report_submitted_at` 에 인덱스를 추가해 full scan을 제거한다.

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c47b3f51ab90'
down_revision: Union[str, Sequence[str], None] = 'b1a7c3d49012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f('ix_buildings_current_phase'),
        'buildings', ['current_phase'], unique=False,
    )
    op.create_index(
        op.f('ix_buildings_final_result'),
        'buildings', ['final_result'], unique=False,
    )
    op.create_index(
        op.f('ix_review_stages_report_submitted_at'),
        'review_stages', ['report_submitted_at'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_review_stages_report_submitted_at'),
        table_name='review_stages',
    )
    op.drop_index(op.f('ix_buildings_final_result'), table_name='buildings')
    op.drop_index(op.f('ix_buildings_current_phase'), table_name='buildings')
