"""notification_logs 발신자 컬럼 추가

Revision ID: 9c1a2b3d4e5f
Revises: f6a4c8d2b901
Create Date: 2026-05-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c1a2b3d4e5f"
down_revision: Union[str, Sequence[str], None] = "f6a4c8d2b901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification_logs",
        sa.Column("sender_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_notification_logs_sender_id_users",
        "notification_logs",
        "users",
        ["sender_id"],
        ["id"],
    )
    op.create_index(
        "ix_notification_logs_sender_id",
        "notification_logs",
        ["sender_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notification_logs_sender_id", table_name="notification_logs")
    op.drop_constraint(
        "fk_notification_logs_sender_id_users",
        "notification_logs",
        type_="foreignkey",
    )
    op.drop_column("notification_logs", "sender_id")
