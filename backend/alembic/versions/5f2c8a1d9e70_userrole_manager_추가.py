"""UserRole에 관리원 추가

Revision ID: 5f2c8a1d9e70
Revises: 8d2b5c9f1a3e
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "5f2c8a1d9e70"
down_revision: Union[str, Sequence[str], None] = "8d2b5c9f1a3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'MANAGER'")


def downgrade() -> None:
    """Downgrade schema.

    PostgreSQL enum value 삭제는 안전하지 않아 되돌리지 않는다.
    """
    pass
