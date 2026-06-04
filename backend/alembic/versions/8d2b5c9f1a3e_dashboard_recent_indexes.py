"""대시보드 최근 목록 조회 인덱스 추가

Revision ID: 8d2b5c9f1a3e
Revises: 7f4d2c1a9b80
Create Date: 2026-06-04 00:00:00.000000

대시보드 첫 화면에서 반복 호출되는 최근 공지/토론/내 알림/내 문의 목록은
`created_at DESC LIMIT 5` 형태로 조회된다. 정렬 비용과 필터 후 정렬을 줄이기
위해 해당 조회 패턴에 맞는 인덱스를 추가한다.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "8d2b5c9f1a3e"
down_revision: Union[str, Sequence[str], None] = "7f4d2c1a9b80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_announcements_created_at",
        "announcements",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_discussions_created_at",
        "discussions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_logs_recipient_id_created_at",
        "notification_logs",
        ["recipient_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_inquiries_submitter_id_created_at",
        "inquiries",
        ["submitter_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inquiries_submitter_id_created_at",
        table_name="inquiries",
    )
    op.drop_index(
        "ix_notification_logs_recipient_id_created_at",
        table_name="notification_logs",
    )
    op.drop_index("ix_discussions_created_at", table_name="discussions")
    op.drop_index("ix_announcements_created_at", table_name="announcements")
