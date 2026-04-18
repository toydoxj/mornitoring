"""services.review_reminder.collect_targets dry-run 회귀 테스트.

도서 접수 없이도 `report_due_date` 만 있으면 트리거 조건에 매칭되는지 확인한다.
카카오 외부 호출은 dry_run 모드에서 일어나지 않으므로 별도 mock 없이도 검증된다.
"""

from datetime import date, timedelta

import pytest

from models.building import Building
from models.review_stage import ReviewStage, PhaseType
from models.user import UserRole
from services.review_reminder import collect_targets, send_review_reminders


def _seed_stage(
    db_session,
    *,
    reviewer_id: int,
    mgmt_no: str,
    due: date,
    submitted: bool = False,
) -> Building:
    b = Building(
        mgmt_no=mgmt_no,
        reviewer_id=reviewer_id,
        assigned_reviewer_name="assigned",
    )
    db_session.add(b)
    db_session.flush()
    db_session.add(ReviewStage(
        building_id=b.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=due - timedelta(days=14),
        report_due_date=due,
        report_submitted_at=due if submitted else None,
    ))
    db_session.commit()
    return b


def test_collect_targets_d_minus_1(db_session, make_reviewer):
    _, reviewer, _ = make_reviewer()
    today = date(2026, 4, 19)
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="R-0001", due=today + timedelta(days=1))
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="R-0002", due=today + timedelta(days=2))
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="R-0003", due=today - timedelta(days=1))

    targets = collect_targets(db_session, "d_minus_1", today=today)
    mgmts = [t.mgmt_no for t in targets]
    assert mgmts == ["R-0001"]


def test_collect_targets_overdue_excludes_submitted(db_session, make_reviewer):
    _, reviewer, _ = make_reviewer()
    today = date(2026, 4, 19)
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="R-0100", due=today - timedelta(days=1))
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="R-0101", due=today - timedelta(days=5), submitted=True)
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="R-0102", due=today, submitted=False)

    targets = collect_targets(db_session, "overdue", today=today)
    mgmts = sorted(t.mgmt_no for t in targets)
    assert mgmts == ["R-0100"]


def test_collect_targets_within_3_days_includes_overdue_and_future(db_session, make_reviewer):
    _, reviewer, _ = make_reviewer()
    today = date(2026, 4, 19)
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="W-001", due=today - timedelta(days=1))  # overdue
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="W-002", due=today)                     # D-day
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="W-003", due=today + timedelta(days=3)) # D-3
    _seed_stage(db_session, reviewer_id=reviewer.id, mgmt_no="W-004", due=today + timedelta(days=4)) # 범위 밖

    mgmts = sorted(t.mgmt_no for t in collect_targets(db_session, "within_3_days", today=today))
    assert mgmts == ["W-001", "W-002", "W-003"]


@pytest.mark.asyncio
async def test_send_review_reminders_respects_recipient_filter(db_session, make_user, make_reviewer):
    sender, _ = make_user(UserRole.CHIEF_SECRETARY, name="발신자")
    _, reviewer_a, _ = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    today = date(2026, 4, 19)
    tomorrow = today + timedelta(days=1)
    _seed_stage(db_session, reviewer_id=reviewer_a.id, mgmt_no="F-001", due=tomorrow)
    _seed_stage(db_session, reviewer_id=reviewer_b.id, mgmt_no="F-002", due=tomorrow)

    result = await send_review_reminders(
        db_session, sender, "d_minus_1",
        dry_run=True, today=today,
        recipient_user_ids=[reviewer_a.user_id],
    )
    assert result["target_count"] == 1
    assert len(result["by_reviewer"]) == 1
    assert result["by_reviewer"][0]["mgmt_nos"] == ["F-001"]


@pytest.mark.asyncio
async def test_send_review_reminders_dry_run_groups_by_reviewer(db_session, make_user, make_reviewer):
    sender, _ = make_user(UserRole.CHIEF_SECRETARY, name="발신자")
    _, reviewer_a, _ = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    today = date(2026, 4, 19)
    tomorrow = today + timedelta(days=1)
    _seed_stage(db_session, reviewer_id=reviewer_a.id, mgmt_no="D-001", due=tomorrow)
    _seed_stage(db_session, reviewer_id=reviewer_a.id, mgmt_no="D-002", due=tomorrow)
    _seed_stage(db_session, reviewer_id=reviewer_b.id, mgmt_no="D-003", due=tomorrow)

    result = await send_review_reminders(
        db_session, sender, "d_minus_1", dry_run=True, today=today
    )
    assert result["target_count"] == 3
    assert result["dry_run"] is True
    # 검토위원별 2명으로 묶여야 함
    assert len(result["by_reviewer"]) == 2
    counts = sorted(r["count"] for r in result["by_reviewer"])
    assert counts == [1, 2]
