"""/api/buildings/reviewer-schedule 엔드포인트 회귀 테스트.

검토위원별 미제출 건을 오늘 기준 D-3/D-2/D-1/D-day/overdue 버킷으로 집계하는지,
REVIEWER 권한은 차단되는지 확인.
"""

from datetime import date, timedelta

from models.building import Building
from models.review_stage import ReviewStage, PhaseType
from models.user import UserRole


def _seed(
    db_session,
    reviewer_id: int,
    mgmt_no: str,
    due: date | None,
    *,
    submitted: date | None = None,
):
    b = Building(mgmt_no=mgmt_no, reviewer_id=reviewer_id, assigned_reviewer_name="assigned")
    db_session.add(b)
    db_session.flush()
    db_session.add(ReviewStage(
        building_id=b.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=due - timedelta(days=14) if due else None,
        report_due_date=due,
        report_submitted_at=submitted,
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
    # 활성 사용자 전원(관리자 + 검토위원) 포함
    assert len(rows) >= 2
    row = next(r for r in rows if r["reviewer_name"].startswith("검토위원"))
    assert row["in_progress"] == 5
    assert row["overdue"] == 1
    assert row["d_day"] == 1
    assert row["d_minus_1"] == 1
    assert row["d_minus_3"] == 1


def test_reviewer_schedule_denied_for_reviewer(client, make_reviewer):
    _, _reviewer, headers = make_reviewer()
    res = client.get("/api/buildings/reviewer-schedule", headers=headers)
    assert res.status_code == 403


def test_reviewer_schedule_on_time_rate(client, db_session, make_user, make_reviewer):
    """마감 경과 건 중 정시 제출 비율을 on_time_rate 로 노출한다."""
    _, headers_admin = make_user(UserRole.CHIEF_SECRETARY, name="관리자")
    _, reviewer, _ = make_reviewer()
    today = date.today()
    # 정시 제출 2건
    _seed(db_session, reviewer.id, "OT-001", today - timedelta(days=5),
          submitted=today - timedelta(days=6))
    _seed(db_session, reviewer.id, "OT-002", today - timedelta(days=3),
          submitted=today - timedelta(days=3))
    # 지연 제출 1건 (마감 하루 뒤 제출)
    _seed(db_session, reviewer.id, "OT-003", today - timedelta(days=4),
          submitted=today - timedelta(days=3))
    # 마감 경과 후 미제출 1건
    _seed(db_session, reviewer.id, "OT-004", today - timedelta(days=1))
    # 마감 미경과 미제출 — 분모에 들어가지 않음
    _seed(db_session, reviewer.id, "OT-005", today + timedelta(days=2))

    res = client.get("/api/buildings/reviewer-schedule", headers=headers_admin)
    assert res.status_code == 200
    row = next(r for r in res.json() if r["reviewer_name"].startswith("검토위원"))
    # 정시 2건 / 마감 경과 4건 → 50%
    assert row["on_time_rate"] == 50


def test_reviewer_schedule_on_time_rate_null_when_nothing_due(
    client, db_session, make_user, make_reviewer
):
    """마감 경과 건이 하나도 없으면 on_time_rate 는 null."""
    _, headers_admin = make_user(UserRole.CHIEF_SECRETARY, name="관리자")
    _, reviewer, _ = make_reviewer()
    today = date.today()
    _seed(db_session, reviewer.id, "FT-001", today + timedelta(days=5))  # 미래만

    res = client.get("/api/buildings/reviewer-schedule", headers=headers_admin)
    assert res.status_code == 200
    row = next(r for r in res.json() if r["reviewer_name"].startswith("검토위원"))
    assert row["on_time_rate"] is None


def test_reviewer_schedule_lists_all_active_users_even_when_idle(
    client, db_session, make_user, make_reviewer
):
    """미제출 건이 없어도 활성 사용자 전원(팀장·총괄간사·간사·검토위원)을 모든 카운트 0으로 포함한다."""
    _, headers_admin = make_user(UserRole.CHIEF_SECRETARY, name="관리자")
    _busy_user, reviewer_busy, _ = make_reviewer()
    _idle_user, _reviewer_idle, _ = make_reviewer()
    today = date.today()
    _seed(db_session, reviewer_busy.id, "Z-0001", today + timedelta(days=1))

    res = client.get("/api/buildings/reviewer-schedule", headers=headers_admin)
    assert res.status_code == 200
    rows = res.json()
    # 관리자 + 검토위원 2명 모두 응답에 포함
    assert len(rows) == 3
    busy = next(r for r in rows if r["in_progress"] > 0)
    idles = [r for r in rows if r["in_progress"] == 0]
    assert busy["d_minus_1"] == 1
    assert len(idles) == 2  # 관리자 + idle 검토위원
    for r in idles:
        assert r["overdue"] == 0
        assert r["d_minus_1"] == 0
