"""resubmissionstatus enum에 REJECTED(반려) 추가

Revision ID: a3d9e2f45c81
Revises: e8b2f1d64a37
Create Date: 2026-08-13 00:00:00.000000

간사가 재제출 요청을 받아들이지 않고 현행 도서로 검토를 요청하는 '반려' 처리를
도입한다. 처리완료(단계 되돌림 + 예정일 삭제)와 결과가 다르므로 상태를 분리한다.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a3d9e2f45c81'
down_revision: Union[str, Sequence[str], None] = 'e8b2f1d64a37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite 등은 enum을 VARCHAR로 다루므로 변경할 게 없다.
        return
    # ADD VALUE 는 트랜잭션 밖에서 실행해야 안전하므로 autocommit 블록을 쓴다.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE resubmissionstatus ADD VALUE IF NOT EXISTS 'REJECTED'"
        )


def downgrade() -> None:
    """PostgreSQL 은 enum 값 제거를 지원하지 않는다.

    되돌릴 때는 반려 건을 처리완료로 바꾸고 값 자체는 남겨 둔다.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "UPDATE resubmission_requests SET status = 'COMPLETED' "
        "WHERE status = 'REJECTED'"
    )
