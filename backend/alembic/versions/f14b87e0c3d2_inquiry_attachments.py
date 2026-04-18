"""inquiry_attachments 테이블 추가

Revision ID: f14b87e0c3d2
Revises: e5d2a318f790
Create Date: 2026-04-19 00:00:00.000000

문의(question) 및 답변(reply) 첨부파일을 한 테이블에 `kind` 로 구분 저장.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f14b87e0c3d2'
down_revision: Union[str, Sequence[str], None] = 'e5d2a318f790'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'inquiry_attachments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('inquiry_id', sa.Integer(), nullable=False),
        sa.Column(
            'kind',
            sa.Enum('QUESTION', 'REPLY', name='inquiryattachmentkind'),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(['inquiry_id'], ['inquiries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_inquiry_attachments_inquiry_id'),
        'inquiry_attachments', ['inquiry_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_inquiry_attachments_inquiry_id'),
        table_name='inquiry_attachments',
    )
    op.drop_table('inquiry_attachments')
    sa.Enum(name='inquiryattachmentkind').drop(op.get_bind(), checkfirst=True)
