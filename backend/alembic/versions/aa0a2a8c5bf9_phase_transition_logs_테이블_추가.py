"""phase_transition_logs 테이블 추가

Revision ID: aa0a2a8c5bf9
Revises: c4d8b71f9a05
Create Date: 2026-04-23 14:50:15.630944

building.current_phase 전환 영구 로그.
- 관리번호별 빠른 조회용으로 mgmt_no 스냅샷 + 인덱스
- building 사후 삭제 시에도 이력 추적되도록 building_id FK는 SET NULL
- actor_user_id도 SET NULL (사용자 삭제 시 이력은 살림)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aa0a2a8c5bf9'
down_revision: Union[str, Sequence[str], None] = 'c4d8b71f9a05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'phase_transition_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('building_id', sa.Integer(), nullable=True),
        sa.Column('mgmt_no', sa.String(length=50), nullable=False),
        sa.Column('from_phase', sa.String(length=50), nullable=True),
        sa.Column('to_phase', sa.String(length=50), nullable=False),
        sa.Column('trigger', sa.String(length=20), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_phase_transition_logs_building_id'),
        'phase_transition_logs', ['building_id'], unique=False,
    )
    op.create_index(
        op.f('ix_phase_transition_logs_mgmt_no'),
        'phase_transition_logs', ['mgmt_no'], unique=False,
    )
    # 관리번호 기준 타임라인 + building 기준 타임라인 빠른 조회.
    op.create_index(
        'ix_phase_transition_logs_mgmt_no_created_at',
        'phase_transition_logs', ['mgmt_no', 'created_at'], unique=False,
    )
    op.create_index(
        'ix_phase_transition_logs_building_id_created_at',
        'phase_transition_logs', ['building_id', 'created_at'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_phase_transition_logs_building_id_created_at',
        table_name='phase_transition_logs',
    )
    op.drop_index(
        'ix_phase_transition_logs_mgmt_no_created_at',
        table_name='phase_transition_logs',
    )
    op.drop_index(
        op.f('ix_phase_transition_logs_mgmt_no'),
        table_name='phase_transition_logs',
    )
    op.drop_index(
        op.f('ix_phase_transition_logs_building_id'),
        table_name='phase_transition_logs',
    )
    op.drop_table('phase_transition_logs')
