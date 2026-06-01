"""상세체크리스트 의견 테이블 추가

Revision ID: f2b1c7d9e4a0
Revises: d4f6e8a1b2c3
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2b1c7d9e4a0"
down_revision: Union[str, Sequence[str], None] = "d4f6e8a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "checklist_opinions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_key", sa.String(length=80), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("author_name", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_checklist_opinions_author_id"),
        "checklist_opinions",
        ["author_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_checklist_opinions_item_key"),
        "checklist_opinions",
        ["item_key"],
        unique=False,
    )
    op.create_index(
        "ix_checklist_opinions_item_key_created_at",
        "checklist_opinions",
        ["item_key", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_checklist_opinions_item_key_created_at",
        table_name="checklist_opinions",
    )
    op.drop_index(
        op.f("ix_checklist_opinions_item_key"),
        table_name="checklist_opinions",
    )
    op.drop_index(
        op.f("ix_checklist_opinions_author_id"),
        table_name="checklist_opinions",
    )
    op.drop_table("checklist_opinions")
