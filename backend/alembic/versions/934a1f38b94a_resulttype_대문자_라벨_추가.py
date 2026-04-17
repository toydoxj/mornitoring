"""ResultType 대문자 라벨 추가

Revision ID: 934a1f38b94a
Revises: e5822b439e6b
Create Date: 2026-04-17 17:05:00.796301

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '934a1f38b94a'
down_revision: Union[str, Sequence[str], None] = 'e5822b439e6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    기존 Postgres enum 'resulttype'의 라벨은 대문자(PASS, SUPPLEMENT, FAIL, MINOR).
    직전 마이그레이션에서 소문자(simple_error, recalculate)를 추가했지만 SQLAlchemy는
    enum 멤버 name(대문자)을 전송하므로 매칭되지 않아 에러. 대문자 라벨을 추가한다.
    """
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE resulttype ADD VALUE IF NOT EXISTS 'SIMPLE_ERROR'")
        op.execute("ALTER TYPE resulttype ADD VALUE IF NOT EXISTS 'RECALCULATE'")


def downgrade() -> None:
    """Downgrade schema. Postgres는 enum value 삭제 미지원."""
    pass
