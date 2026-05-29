"""검토서 분류별 심각도 집계 테이블 추가

Revision ID: b7c9d2e4f6a8
Revises: a4f2c7e9d8b1
Create Date: 2026-05-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c9d2e4f6a8"
down_revision: Union[str, Sequence[str], None] = "a4f2c7e9d8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_severity_summaries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stage_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("severity", sa.String(length=2), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stage_id"], ["review_stages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stage_id",
            "category",
            "severity",
            name="uq_review_severity_summary_stage_category_severity",
        ),
    )
    op.create_index(
        "ix_review_severity_summaries_stage_id",
        "review_severity_summaries",
        ["stage_id"],
    )
    op.create_index(
        "ix_review_severity_summaries_category",
        "review_severity_summaries",
        ["category"],
    )
    op.create_index(
        "ix_review_severity_summaries_severity",
        "review_severity_summaries",
        ["severity"],
    )
    op.create_index(
        "ix_review_severity_summaries_category_severity",
        "review_severity_summaries",
        ["category", "severity"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_severity_summaries_category_severity",
        table_name="review_severity_summaries",
    )
    op.drop_index(
        "ix_review_severity_summaries_severity",
        table_name="review_severity_summaries",
    )
    op.drop_index(
        "ix_review_severity_summaries_category",
        table_name="review_severity_summaries",
    )
    op.drop_index(
        "ix_review_severity_summaries_stage_id",
        table_name="review_severity_summaries",
    )
    op.drop_table("review_severity_summaries")
