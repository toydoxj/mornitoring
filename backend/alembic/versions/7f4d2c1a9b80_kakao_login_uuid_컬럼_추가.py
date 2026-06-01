"""카카오 로그인 uuid 컬럼 추가

Revision ID: 7f4d2c1a9b80
Revises: f2b1c7d9e4a0
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7f4d2c1a9b80"
down_revision: Union[str, Sequence[str], None] = "f2b1c7d9e4a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("kakao_login_uuid", sa.String(length=100), nullable=True))
    op.add_column(
        "kakao_link_sessions",
        sa.Column("kakao_login_uuid", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("kakao_link_sessions", "kakao_login_uuid")
    op.drop_column("users", "kakao_login_uuid")
