"""resubmission_requests.re_received_at 컬럼 추가

Revision ID: e8b2f1d64a37
Revises: d1c3a5b70e42
Create Date: 2026-08-13 00:00:00.000000

재제출 요청 이후 도서가 다시 접수된 시각을 기록한다. 도서 재접수 시
검토서 요청 예정일을 비우는 대상을 "아직 재접수되지 않은 대기 요청"으로
한정하기 위해 사용한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8b2f1d64a37'
down_revision: Union[str, Sequence[str], None] = 'd1c3a5b70e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'resubmission_requests',
        sa.Column('re_received_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('resubmission_requests', 're_received_at')
