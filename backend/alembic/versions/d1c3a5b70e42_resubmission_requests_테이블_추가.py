"""resubmission_requests 테이블 추가

Revision ID: d1c3a5b70e42
Revises: ('b53ed7c91f48', 'c7e1f30ab924')
Create Date: 2026-08-13 00:00:00.000000

검토위원의 설계도서 재제출 요청을 기록한다. 요청 시 building.current_phase 는
접수 직전 단계로 되돌아가고 해당 단계의 report_due_date 가 비워지며, 사유는
간사·관리원이 별도 메뉴에서 확인한다.

기존에 갈라져 있던 두 head(b53ed7c91f48: 검토위원 조 편성,
c7e1f30ab924: 배포차수 기준 단계)를 함께 병합한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1c3a5b70e42'
down_revision: Union[str, Sequence[str], None] = ('b53ed7c91f48', 'c7e1f30ab924')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'resubmission_requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('building_id', sa.Integer(), nullable=True),
        sa.Column('mgmt_no', sa.String(length=20), nullable=False),
        sa.Column('phase', sa.String(length=30), nullable=False),
        sa.Column('from_phase', sa.String(length=30), nullable=True),
        sa.Column('to_phase', sa.String(length=30), nullable=True),
        sa.Column('cleared_due_date', sa.String(length=10), nullable=True),
        sa.Column('requester_id', sa.Integer(), nullable=True),
        sa.Column('requester_name', sa.String(length=50), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('PENDING', 'COMPLETED', name='resubmissionstatus'),
            nullable=False,
            server_default='PENDING',
        ),
        sa.Column('reply', sa.Text(), nullable=True),
        sa.Column('handled_by', sa.Integer(), nullable=True),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['requester_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['handled_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_resubmission_requests_building_id'),
        'resubmission_requests', ['building_id'], unique=False,
    )
    op.create_index(
        op.f('ix_resubmission_requests_mgmt_no'),
        'resubmission_requests', ['mgmt_no'], unique=False,
    )
    op.create_index(
        op.f('ix_resubmission_requests_requester_id'),
        'resubmission_requests', ['requester_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_resubmission_requests_requester_id'),
        table_name='resubmission_requests',
    )
    op.drop_index(
        op.f('ix_resubmission_requests_mgmt_no'),
        table_name='resubmission_requests',
    )
    op.drop_index(
        op.f('ix_resubmission_requests_building_id'),
        table_name='resubmission_requests',
    )
    op.drop_table('resubmission_requests')
    sa.Enum(name='resubmissionstatus').drop(op.get_bind(), checkfirst=True)
