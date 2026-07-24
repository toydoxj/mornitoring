"""inappropriate_decision enum에 COLLAPSE_RISK(붕괴우려) 추가

확정(심각)보다 상위 단계인 '붕괴우려' 판정을 부적합 검토에 도입한다.

Revision ID: e2a4c6b8d013
Revises: d9f1a2b3c4d5
Create Date: 2026-07-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e2a4c6b8d013'
down_revision: Union[str, Sequence[str], None] = 'd9f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite 등 비-PostgreSQL 환경은 enum을 VARCHAR로 다루므로 변경할 게 없다.
        return
    # PostgreSQL enum 정렬 순서상 확정(심각) 바로 앞(= 상위 단계)에 배치한다.
    # ADD VALUE 는 트랜잭션 밖에서 실행해야 안전하므로 autocommit 블록을 쓴다.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE inappropriatedecision "
            "ADD VALUE IF NOT EXISTS 'COLLAPSE_RISK' BEFORE 'CONFIRMED_SERIOUS'"
        )


def downgrade() -> None:
    """Downgrade schema.

    PostgreSQL 은 enum 값 제거를 지원하지 않는다. 되돌릴 때는 해당 값을 쓰던
    행을 확정(심각)으로 내리고 값 자체는 남겨 둔다.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "UPDATE review_stages SET inappropriate_decision = 'CONFIRMED_SERIOUS' "
        "WHERE inappropriate_decision = 'COLLAPSE_RISK'"
    )
