"""ResultType을 3종(pass/simple_error/recalculate)으로 정리

Revision ID: 65678b8e44dc
Revises: 934a1f38b94a
Create Date: 2026-04-17 17:12:24.340862

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65678b8e44dc'
down_revision: Union[str, Sequence[str], None] = '934a1f38b94a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    기존 ResultType 6종 → 3종으로 정리.
    - SUPPLEMENT, FAIL → RECALCULATE
    - MINOR → SIMPLE_ERROR
    - 대소문자 혼재된 기존 값도 정규화

    buildings.final_result(varchar) 도 소문자 3종으로 정규화.
    """
    # 1. review_stages.result 값을 3종(대문자)으로 통일
    op.execute("""
        UPDATE review_stages SET result = 'RECALCULATE'
        WHERE result::text IN ('SUPPLEMENT', 'supplement', 'FAIL', 'fail', 'recalculate')
    """)
    op.execute("""
        UPDATE review_stages SET result = 'SIMPLE_ERROR'
        WHERE result::text IN ('MINOR', 'minor', 'simple_error')
    """)
    op.execute("""
        UPDATE review_stages SET result = 'PASS'
        WHERE result::text = 'pass'
    """)

    # 2. buildings.final_result(varchar) 소문자 3종 정규화
    op.execute("""
        UPDATE buildings SET final_result = 'recalculate'
        WHERE final_result IN ('supplement', 'fail', 'SUPPLEMENT', 'FAIL', 'RECALCULATE')
    """)
    op.execute("""
        UPDATE buildings SET final_result = 'simple_error'
        WHERE final_result IN ('minor', 'MINOR', 'SIMPLE_ERROR')
    """)
    op.execute("""
        UPDATE buildings SET final_result = 'pass' WHERE final_result = 'PASS'
    """)

    # 3. enum 타입 재생성: 기존 타입을 drop하고 3종만 가진 새 타입으로 교체
    op.execute("CREATE TYPE resulttype_new AS ENUM ('PASS', 'SIMPLE_ERROR', 'RECALCULATE')")
    op.execute("""
        ALTER TABLE review_stages
        ALTER COLUMN result TYPE resulttype_new
        USING result::text::resulttype_new
    """)
    op.execute("DROP TYPE resulttype")
    op.execute("ALTER TYPE resulttype_new RENAME TO resulttype")


def downgrade() -> None:
    """Downgrade는 구현하지 않음 (데이터 손실 방지)."""
    pass
