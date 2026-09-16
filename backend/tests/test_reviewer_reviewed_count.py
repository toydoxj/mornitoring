"""검토위원별 현황 '검토완료' 집계 회귀 테스트.

검토완료 = 검토서를 한 장이라도 제출한 건물(관리번호) 수.
한 건물에서 예비·1차·2차를 몇 장 내든 1로 센다.
"""

from datetime import datetime

from models.review_stage import PhaseType, ReviewStage
from models.user import UserRole


PHASE_ORDER = {
    PhaseType.PRELIMINARY: 0,
    PhaseType.SUPPLEMENT_1: 1,
    PhaseType.SUPPLEMENT_2: 2,
}


def _add_stage(db_session, building, phase, *, submitted: bool):
    """건물에 검토 단계를 붙인다. submitted=False면 도서 접수만 된 상태."""
    stage = ReviewStage(
        building_id=building.id,
        phase=phase,
        phase_order=PHASE_ORDER[phase],
        doc_received_at=datetime(2026, 3, 2),
        report_submitted_at=datetime(2026, 3, 10) if submitted else None,
        reviewer_name="검토위원1" if submitted else None,
    )
    db_session.add(stage)
    db_session.commit()
    return stage


def _reviewer_row(client, headers, name):
    res = client.get("/api/buildings/stats?scope=all", headers=headers)
    assert res.status_code == 200, res.text
    rows = res.json()["reviewer_stats"]
    return next(row for row in rows if row["name"] == name)


def test_multiple_reports_on_one_building_count_as_one(
    client, db_session, make_user, make_reviewer, make_building
):
    """한 건물에 예비+1차 2장을 내도 검토완료는 1건이다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0001", reviewer_id=reviewer.id)
    _add_stage(db_session, building, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, building, PhaseType.SUPPLEMENT_1, submitted=True)

    row = _reviewer_row(client, headers, "검토위원1")
    assert row["reviewed"] == 1
    # 검토서 장수는 기존 열이 그대로 2장으로 센다
    assert row["preliminary"]["report_submitted"] == 1
    assert row["supplement"]["report_submitted"] == 1


def test_preliminary_only_counts_as_one(
    client, db_session, make_user, make_reviewer, make_building
):
    """예비검토서만 제출해도 1건이다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0002", reviewer_id=reviewer.id)
    _add_stage(db_session, building, PhaseType.PRELIMINARY, submitted=True)

    assert _reviewer_row(client, headers, "검토위원1")["reviewed"] == 1


def test_supplement_only_counts_as_one(
    client, db_session, make_user, make_reviewer, make_building
):
    """예비 없이 1차 보완검토서만 제출해도 1건이다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0003", reviewer_id=reviewer.id)
    _add_stage(db_session, building, PhaseType.SUPPLEMENT_1, submitted=True)

    assert _reviewer_row(client, headers, "검토위원1")["reviewed"] == 1


def test_three_phases_on_one_building_count_as_one(
    client, db_session, make_user, make_reviewer, make_building
):
    """예비·1차·2차까지 진행돼도 건물 1개면 1건이다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0004", reviewer_id=reviewer.id)
    for phase in (PhaseType.PRELIMINARY, PhaseType.SUPPLEMENT_1, PhaseType.SUPPLEMENT_2):
        _add_stage(db_session, building, phase, submitted=True)

    assert _reviewer_row(client, headers, "검토위원1")["reviewed"] == 1


def test_unsubmitted_stage_is_not_counted(
    client, db_session, make_user, make_reviewer, make_building
):
    """도서만 접수되고 검토서가 없으면 검토완료에 들어가지 않는다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0005", reviewer_id=reviewer.id)
    _add_stage(db_session, building, PhaseType.PRELIMINARY, submitted=False)

    row = _reviewer_row(client, headers, "검토위원1")
    assert row["reviewed"] == 0
    assert row["total"] == 1


def test_reviewed_counts_distinct_buildings(
    client, db_session, make_user, make_reviewer, make_building
):
    """건물이 여러 개면 검토서를 낸 건물 수만큼 센다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    b1 = make_building(mgmt_no="RVW-0006", reviewer_id=reviewer.id)
    b2 = make_building(mgmt_no="RVW-0007", reviewer_id=reviewer.id)
    b3 = make_building(mgmt_no="RVW-0008", reviewer_id=reviewer.id)
    _add_stage(db_session, b1, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, b1, PhaseType.SUPPLEMENT_1, submitted=True)
    _add_stage(db_session, b2, PhaseType.SUPPLEMENT_1, submitted=True)
    _add_stage(db_session, b3, PhaseType.PRELIMINARY, submitted=False)

    row = _reviewer_row(client, headers, "검토위원1")
    assert row["total"] == 3
    assert row["reviewed"] == 2


def test_reviewer_without_any_stage_has_zero(
    client, db_session, make_user, make_reviewer, make_building
):
    """검토 단계가 아예 없는 위원도 0으로 응답에 포함된다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=2)
    rev_user.name = "검토위원2"
    db_session.commit()

    make_building(mgmt_no="RVW-0009", reviewer_id=reviewer.id)

    row = _reviewer_row(client, headers, "검토위원2")
    assert row["reviewed"] == 0


def test_name_only_assignment_is_counted(
    client, db_session, make_user, make_building
):
    """Reviewer 계정 없이 이름만 배정된 건물도 그 이름으로 집계된다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)

    building = make_building(mgmt_no="RVW-0010")
    building.assigned_reviewer_name = "이름만위원"
    db_session.commit()
    _add_stage(db_session, building, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, building, PhaseType.SUPPLEMENT_1, submitted=True)

    row = _reviewer_row(client, headers, "이름만위원")
    assert row["total"] == 1
    assert row["reviewed"] == 1


def test_reviewed_is_split_per_reviewer(
    client, db_session, make_user, make_reviewer, make_building
):
    """위원이 여럿이면 각자의 건물만 센다 (합계행 단순 합산의 전제)."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    user_a, rev_a, _ = make_reviewer(group_no=1)
    user_a.name = "위원A"
    user_b, rev_b, _ = make_reviewer(group_no=2)
    user_b.name = "위원B"
    db_session.commit()

    a1 = make_building(mgmt_no="RVW-0011", reviewer_id=rev_a.id)
    a2 = make_building(mgmt_no="RVW-0012", reviewer_id=rev_a.id)
    b1 = make_building(mgmt_no="RVW-0013", reviewer_id=rev_b.id)
    _add_stage(db_session, a1, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, a1, PhaseType.SUPPLEMENT_1, submitted=True)
    _add_stage(db_session, a2, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, b1, PhaseType.PRELIMINARY, submitted=True)

    res = client.get("/api/buildings/stats?scope=all", headers=headers)
    rows = {row["name"]: row for row in res.json()["reviewer_stats"]}
    assert rows["위원A"]["reviewed"] == 2
    assert rows["위원B"]["reviewed"] == 1
    # 합계행은 프론트에서 단순 합산한다 — 건물 3개 중 검토서가 있는 건 3개
    assert sum(row["reviewed"] for row in rows.values()) == 3
