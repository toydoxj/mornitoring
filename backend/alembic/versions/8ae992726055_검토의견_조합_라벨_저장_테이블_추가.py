"""검토의견 조합 라벨 저장 테이블 추가

Revision ID: 8ae992726055
Revises: b8f2c1d47e90
Create Date: 2026-09-03 10:48:01.169570

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ae992726055'
down_revision: Union[str, Sequence[str], None] = 'b8f2c1d47e90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 조합 라벨(opinion_combination_labels)과 라벨링 작업 이력(opinion_label_runs) 추가.
    # autogenerate가 함께 만들어낸 기존 성능 인덱스 drop 구문은 제거했다.
    # 그 인덱스들은 모델에 선언하지 않고 별도 마이그레이션으로 만든 것이라
    # 모델 기준 비교에서 "삭제됨"으로 잡힐 뿐 실제로는 유지해야 한다.
    op.create_table('opinion_combination_labels',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('detail_id', sa.Integer(), nullable=False),
    sa.Column('primary_target', sa.String(length=40), nullable=False),
    sa.Column('secondary_target', sa.String(length=40), server_default='', nullable=False),
    sa.Column('issue_type', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=10), server_default='rule', nullable=False),
    sa.Column('ruleset_version', sa.String(length=20), nullable=True),
    sa.Column('taxonomy_version', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['detail_id'], ['review_opinion_details.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('detail_id', 'primary_target', 'secondary_target', 'issue_type', name='uq_opinion_combination_label')
    )
    op.create_index(op.f('ix_opinion_combination_labels_detail_id'), 'opinion_combination_labels', ['detail_id'], unique=False)
    op.create_index(op.f('ix_opinion_combination_labels_issue_type'), 'opinion_combination_labels', ['issue_type'], unique=False)
    op.create_index(op.f('ix_opinion_combination_labels_primary_target'), 'opinion_combination_labels', ['primary_target'], unique=False)
    op.create_table('opinion_label_runs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('detail_id', sa.Integer(), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('ruleset_version', sa.String(length=20), nullable=True),
    sa.Column('taxonomy_version', sa.String(length=20), nullable=True),
    sa.Column('llm_contract_version', sa.String(length=20), nullable=True),
    sa.Column('requested_model', sa.String(length=60), nullable=True),
    sa.Column('resolved_model', sa.String(length=60), nullable=True),
    sa.Column('status', sa.String(length=12), server_default='pending', nullable=False),
    sa.Column('unmatched_reason', sa.String(length=20), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['detail_id'], ['review_opinion_details.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('detail_id', 'input_hash', name='uq_opinion_label_run_input')
    )
    op.create_index(op.f('ix_opinion_label_runs_detail_id'), 'opinion_label_runs', ['detail_id'], unique=False)
    op.create_index(op.f('ix_opinion_label_runs_status'), 'opinion_label_runs', ['status'], unique=False)
    op.create_index(op.f('ix_opinion_label_runs_unmatched_reason'), 'opinion_label_runs', ['unmatched_reason'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_opinion_label_runs_unmatched_reason'), table_name='opinion_label_runs')
    op.drop_index(op.f('ix_opinion_label_runs_status'), table_name='opinion_label_runs')
    op.drop_index(op.f('ix_opinion_label_runs_detail_id'), table_name='opinion_label_runs')
    op.drop_table('opinion_label_runs')
    op.drop_index(op.f('ix_opinion_combination_labels_primary_target'), table_name='opinion_combination_labels')
    op.drop_index(op.f('ix_opinion_combination_labels_issue_type'), table_name='opinion_combination_labels')
    op.drop_index(op.f('ix_opinion_combination_labels_detail_id'), table_name='opinion_combination_labels')
    op.drop_table('opinion_combination_labels')
