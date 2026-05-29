"""내 검토 대상 조회 인덱스 추가

Revision ID: f6a4c8d2b901
Revises: b53ed7c91f48
Create Date: 2026-05-29 00:00:00.000000

`/api/buildings/my-reviews` 는 reviewer_id로 건물을 찾고 mgmt_no로 정렬한 뒤,
페이지 내 건물의 최신 검토 단계와 미제출 예정일 단계를 조회한다. 이 경로의
full scan과 정렬 비용을 줄이기 위해 복합 인덱스를 추가한다.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f6a4c8d2b901"
down_revision: Union[str, Sequence[str], None] = "b53ed7c91f48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_buildings_reviewer_id_mgmt_no",
        "buildings",
        ["reviewer_id", "mgmt_no"],
        unique=False,
    )
    op.create_index(
        "ix_review_stages_building_phase_order",
        "review_stages",
        ["building_id", "phase_order"],
        unique=False,
    )
    op.create_index(
        "ix_review_stages_building_submitted_phase_order",
        "review_stages",
        ["building_id", "report_submitted_at", "phase_order"],
        unique=False,
    )
    op.create_index(
        "ix_review_stages_building_due_phase_order",
        "review_stages",
        ["building_id", "report_due_date", "phase_order"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_stages_building_due_phase_order",
        table_name="review_stages",
    )
    op.drop_index(
        "ix_review_stages_building_submitted_phase_order",
        table_name="review_stages",
    )
    op.drop_index(
        "ix_review_stages_building_phase_order",
        table_name="review_stages",
    )
    op.drop_index("ix_buildings_reviewer_id_mgmt_no", table_name="buildings")
