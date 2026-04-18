"""댓글 첨부 테이블 + 기존 첨부에 content_type 컬럼

Revision ID: e5d2a318f790
Revises: d7e914c80f52
Create Date: 2026-04-19 00:00:00.000000

공지사항/토론방 댓글에도 파일 첨부를 허용하기 위해 두 개의 신규 테이블을 만들고,
기존 Announcement/DiscussionAttachment 에는 이미지 인라인 렌더에 필요한
`content_type` 컬럼을 nullable 로 추가한다.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5d2a318f790'
down_revision: Union[str, Sequence[str], None] = 'd7e914c80f52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 기존 첨부 테이블에 content_type 컬럼 추가
    op.add_column(
        'announcement_attachments',
        sa.Column('content_type', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'discussion_attachments',
        sa.Column('content_type', sa.String(length=100), nullable=True),
    )

    # 2) 공지사항 댓글 첨부 테이블
    op.create_table(
        'announcement_comment_attachments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('comment_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('s3_key', sa.String(length=500), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['comment_id'], ['announcement_comments.id'], ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_announcement_comment_attachments_comment_id'),
        'announcement_comment_attachments', ['comment_id'], unique=False,
    )

    # 3) 토론방 댓글 첨부 테이블
    op.create_table(
        'discussion_comment_attachments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('comment_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('s3_key', sa.String(length=500), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['comment_id'], ['discussion_comments.id'], ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_discussion_comment_attachments_comment_id'),
        'discussion_comment_attachments', ['comment_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_discussion_comment_attachments_comment_id'),
        table_name='discussion_comment_attachments',
    )
    op.drop_table('discussion_comment_attachments')

    op.drop_index(
        op.f('ix_announcement_comment_attachments_comment_id'),
        table_name='announcement_comment_attachments',
    )
    op.drop_table('announcement_comment_attachments')

    op.drop_column('discussion_attachments', 'content_type')
    op.drop_column('announcement_attachments', 'content_type')
