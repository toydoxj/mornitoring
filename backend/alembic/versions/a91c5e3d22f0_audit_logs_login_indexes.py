"""감사 로그 조회 성능: 로그인 이력 인덱스 추가

Revision ID: a91c5e3d22f0
Revises: f14b87e0c3d2
Create Date: 2026-04-20 00:00:00.000000

`/api/audit-logs/logins` 와 사용자 활동 추적이 잦아질 것을 대비해
`audit_logs(action, created_at)` 와 `audit_logs(user_id, created_at)` 복합 인덱스를 추가.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a91c5e3d22f0'
down_revision: Union[str, Sequence[str], None] = 'f14b87e0c3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_audit_logs_action_created_at',
        'audit_logs', ['action', 'created_at'], unique=False,
    )
    op.create_index(
        'ix_audit_logs_user_id_created_at',
        'audit_logs', ['user_id', 'created_at'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_audit_logs_user_id_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action_created_at', table_name='audit_logs')
