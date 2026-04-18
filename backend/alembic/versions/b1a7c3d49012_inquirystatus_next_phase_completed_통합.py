"""inquirystatus next_phase를 completed로 통합

Revision ID: b1a7c3d49012
Revises: 34755893cd3c
Create Date: 2026-04-18 00:00:00.000000

기존 inquiries.status='NEXT_PHASE' 데이터를 'COMPLETED'로 전환하고,
inquirystatus enum에서 NEXT_PHASE 값을 제거한다.

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b1a7c3d49012'
down_revision: Union[str, Sequence[str], None] = '34755893cd3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1) 남아 있는 NEXT_PHASE 문의를 COMPLETED로 통합
    op.execute("UPDATE inquiries SET status='COMPLETED' WHERE status='NEXT_PHASE'")

    # 2) 새 enum 타입 생성 (NEXT_PHASE 제외)
    op.execute(
        "CREATE TYPE inquirystatus_new AS ENUM ('OPEN', 'ASKING_AGENCY', 'COMPLETED')"
    )

    # 3) 컬럼을 새 enum 타입으로 교체
    op.execute(
        "ALTER TABLE inquiries "
        "ALTER COLUMN status TYPE inquirystatus_new "
        "USING status::text::inquirystatus_new"
    )

    # 4) 구 enum 제거 후 신 enum 이름 복구
    op.execute("DROP TYPE inquirystatus")
    op.execute("ALTER TYPE inquirystatus_new RENAME TO inquirystatus")


def downgrade() -> None:
    """Downgrade schema."""
    # enum 값 복원. 기존 NEXT_PHASE 데이터는 이미 COMPLETED로 병합되어 복원 불가.
    op.execute(
        "CREATE TYPE inquirystatus_old AS ENUM "
        "('OPEN', 'ASKING_AGENCY', 'COMPLETED', 'NEXT_PHASE')"
    )
    op.execute(
        "ALTER TABLE inquiries "
        "ALTER COLUMN status TYPE inquirystatus_old "
        "USING status::text::inquirystatus_old"
    )
    op.execute("DROP TYPE inquirystatus")
    op.execute("ALTER TYPE inquirystatus_old RENAME TO inquirystatus")
