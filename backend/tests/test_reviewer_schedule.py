"""/api/buildings/reviewer-schedule 엔드포인트 회귀 테스트.

검토위원별 미제출 건을 오늘 기준 D-3/D-2/D-1/D-day/overdue 버킷으로 집계하는지,
REVIEWER 권한은 차단되는지 확인.
"""

from datetime import date, timedelta

from models.building import Building
from models.review_stage import ReviewStage, PhaseType
from models.user import UserRole


def _seed(db_session, reviewer_id: int, mgmt_no: str, due: date | None):
    b = Building(mgmt_no=mgmt_no, reviewer_id=reviewer_id, assigned_reviewer_name="assigned")
    db_session.add(b)
    db_session.flush()
    db_session.add(ReviewStage(
        building_id=b.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=due - timedelta(days=14) if due else None,
        report_due_date=due,
    ))
    db_session.commit()


def test_reviewer_schedule_buckets(client, db_session, make_user, make_reviewer):
    _, headers_admin = make_user(UserRole.CHIEF_SECRETARY, name="관리자")
    _, reviewer, _ = make_reviewer()
    today = date.today()
    _seed(db_session, reviewer.id, "S-001", today - timedelta(days=2))   # overdue
    _seed(db_session, reviewer.id, "S-002", today)                        # d_day
    _seed(db_session, reviewer.id, "S-003", today + timedelta(days=1))    # d_minus_1
    _seed(db_session, reviewer.id, "S-004", today + timedelta(days=3))    # d_minus_3
    _seed(db_session, reviewer.id, "S-005", today + timedelta(days=7))    # 범위 밖 → in_progress만

    res = client.get("/api/buildings/reviewer-schedule", headers=headers_admin)
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["in_progress"] == 5
    assert row["overdue"] == 1
    assert row["d_day"] == 1
    assert row["d_minus_1"] == 1
    assert row["d_minus_3"] == 1


def test_reviewer_schedule_denied_for_reviewer(client, make_reviewer):
    _, _reviewer, headers = make_reviewer()
    res = client.get("/api/buildings/reviewer-schedule", headers=headers)
    assert res.status_code == 403
