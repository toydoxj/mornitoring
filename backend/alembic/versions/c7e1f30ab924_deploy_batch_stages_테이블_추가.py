"""deploy_batch_stages 테이블 추가

Revision ID: c7e1f30ab924
Revises: e2a4c6b8d013
Create Date: 2026-08-12 12:10:00.000000

배포차수(1~5)별 기준 검토 단계를 총괄간사가 지정하기 위한 테이블.
- batch_no는 차수당 1행만 존재하도록 unique
- 행이 없는 차수는 기준 미설정으로 보고 접수 시 보정을 건너뛴다
- 사용자 삭제 시에도 설정은 남겨야 하므로 updated_by_user_id FK는 SET NULL
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e1f30ab924'
down_revision: Union[str, Sequence[str], None] = 'e2a4c6b8d013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'deploy_batch_stages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('batch_no', sa.Integer(), nullable=False),
        sa.Column('phase', sa.String(length=30), nullable=False),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_deploy_batch_stages_batch_no'),
        'deploy_batch_stages', ['batch_no'], unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_deploy_batch_stages_batch_no'),
        table_name='deploy_batch_stages',
    )
    op.drop_table('deploy_batch_stages')
