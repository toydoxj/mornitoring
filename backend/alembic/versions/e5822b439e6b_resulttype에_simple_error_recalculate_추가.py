"""ResultType에 simple_error, recalculate 추가

Revision ID: e5822b439e6b
Revises: 1d79e90f3ebe
Create Date: 2026-04-17 17:01:52.566734

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5822b439e6b'
down_revision: Union[str, Sequence[str], None] = '1d79e90f3ebe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Postgres enum type에 새 값 추가 (IF NOT EXISTS로 idempotent)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE resulttype ADD VALUE IF NOT EXISTS 'simple_error'")
        op.execute("ALTER TYPE resulttype ADD VALUE IF NOT EXISTS 'recalculate'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres는 enum value 삭제를 직접 지원하지 않음 (downgrade 미구현)
    pass
