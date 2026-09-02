"""통계 분석 챗봇 대화 이력 테이블 추가

Revision ID: b8f2c1d47e90
Revises: a3d9e2f45c81
Create Date: 2026-09-02 00:00:00.000000

stats_chat_conversations / stats_chat_messages 두 테이블을 만든다.
신규 public 테이블의 RLS ENABLE/FORCE 는 alembic/env.py 의 post-upgrade 훅이
자동으로 처리하므로 여기서는 별도로 걸지 않는다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b8f2c1d47e90'
down_revision: Union[str, Sequence[str], None] = 'a3d9e2f45c81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stats_chat_conversations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
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
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_stats_chat_conversations_user_id'),
        'stats_chat_conversations',
        ['user_id'],
    )

    op.create_table(
        'stats_chat_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column(
            'role',
            sa.Enum('USER', 'ASSISTANT', name='statschatrole'),
            nullable=False,
        ),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sql_log', sa.Text(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['conversation_id'], ['stats_chat_conversations.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_stats_chat_messages_conversation_id_id',
        'stats_chat_messages',
        ['conversation_id', 'id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_stats_chat_messages_conversation_id_id',
        table_name='stats_chat_messages',
    )
    op.drop_table('stats_chat_messages')
    op.drop_index(
        op.f('ix_stats_chat_conversations_user_id'),
        table_name='stats_chat_conversations',
    )
    op.drop_table('stats_chat_conversations')
    bind = op.get_bind()
    if bind is not None and bind.dialect.name == 'postgresql':
        sa.Enum(name='statschatrole').drop(bind, checkfirst=True)
