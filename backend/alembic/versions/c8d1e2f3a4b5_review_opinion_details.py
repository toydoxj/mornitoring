"""검토서 상세검토 내용 원문 테이블 추가

Revision ID: c8d1e2f3a4b5
Revises: b7c9d2e4f6a8
Create Date: 2026-05-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b7c9d2e4f6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_opinion_details",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stage_id", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=30), nullable=False),
        sa.Column("phase_group", sa.String(length=20), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("severity", sa.String(length=2), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
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
    )
    op.create_index(
        "ix_review_opinion_details_stage_id",
        "review_opinion_details",
        ["stage_id"],
    )
    op.create_index(
        "ix_review_opinion_details_phase",
        "review_opinion_details",
        ["phase"],
    )
    op.create_index(
        "ix_review_opinion_details_phase_group",
        "review_opinion_details",
        ["phase_group"],
    )
    op.create_index(
        "ix_review_opinion_details_category",
        "review_opinion_details",
        ["category"],
    )
    op.create_index(
        "ix_review_opinion_details_severity",
        "review_opinion_details",
        ["severity"],
    )
    op.create_index(
        "ix_review_opinion_details_phase_group_category",
        "review_opinion_details",
        ["phase_group", "category"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_opinion_details_phase_group_category",
        table_name="review_opinion_details",
    )
    op.drop_index(
        "ix_review_opinion_details_severity",
        table_name="review_opinion_details",
    )
    op.drop_index(
        "ix_review_opinion_details_category",
        table_name="review_opinion_details",
    )
    op.drop_index(
        "ix_review_opinion_details_phase_group",
        table_name="review_opinion_details",
    )
    op.drop_index(
        "ix_review_opinion_details_phase",
        table_name="review_opinion_details",
    )
    op.drop_index(
        "ix_review_opinion_details_stage_id",
        table_name="review_opinion_details",
    )
    op.drop_table("review_opinion_details")
