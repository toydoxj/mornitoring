"""조합 라벨에 세부항목 컬럼 추가

Revision ID: c51505aa891d
Revises: 8ae992726055
Create Date: 2026-09-03 14:31:47.736178

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c51505aa891d'
down_revision: Union[str, Sequence[str], None] = '8ae992726055'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 세부항목(aspect) 추가. 기존 행은 빈 문자열이 되어 "세부항목 없음"으로 남는다.
    # autogenerate가 함께 만들어낸 기존 성능 인덱스 drop 구문은 제거했다(오탐).
    op.add_column('opinion_combination_labels', sa.Column('aspect', sa.String(length=30), server_default='', nullable=False))
    op.drop_constraint(op.f('uq_opinion_combination_label'), 'opinion_combination_labels', type_='unique')
    op.create_unique_constraint('uq_opinion_combination_label', 'opinion_combination_labels', ['detail_id', 'primary_target', 'secondary_target', 'aspect', 'issue_type'])
    op.create_index(op.f('ix_opinion_combination_labels_aspect'), 'opinion_combination_labels', ['aspect'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_opinion_combination_labels_aspect'), table_name='opinion_combination_labels')
    op.drop_constraint('uq_opinion_combination_label', 'opinion_combination_labels', type_='unique')
    op.create_unique_constraint(op.f('uq_opinion_combination_label'), 'opinion_combination_labels', ['detail_id', 'primary_target', 'secondary_target', 'issue_type'], postgresql_nulls_not_distinct=False)
    op.drop_column('opinion_combination_labels', 'aspect')
