"""검토의견 표현 품질 판정 컬럼 추가

Revision ID: d9f1a2b3c4d5
Revises: b3c4d5e6f7a8
Create Date: 2026-06-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "review_opinion_details",
        sa.Column(
            "quality_decision",
            sa.String(length=20),
            server_default="unsuitable",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_review_opinion_details_quality_decision",
        "review_opinion_details",
        ["quality_decision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_opinion_details_quality_decision",
        table_name="review_opinion_details",
    )
    op.drop_column("review_opinion_details", "quality_decision")
