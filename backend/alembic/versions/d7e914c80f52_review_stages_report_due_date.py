"""review_stages.report_due_date 추가

Revision ID: d7e914c80f52
Revises: c47b3f51ab90
Create Date: 2026-04-19 00:00:00.000000

도서 접수 시점에 검토위원에게 요청할 예정일을 저장하기 위한 DATE 컬럼.
기본값 없음(NULL). 기존 historical 데이터는 NULL 상태로 유지되며, 신규 접수부터
프론트/백엔드 로직이 기본(접수일 + 14일) 또는 수동 입력값을 채운다.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e914c80f52'
down_revision: Union[str, Sequence[str], None] = 'c47b3f51ab90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'review_stages',
        sa.Column('report_due_date', sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('review_stages', 'report_due_date')
