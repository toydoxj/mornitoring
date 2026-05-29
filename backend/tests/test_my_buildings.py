"""buildings /my-stats, /my-reviews 회귀 테스트.

N2 변경 후: 담당 매칭은 reviewer_id만 사용. 이름 기반 OR 매칭 제거.
- Reviewer 행이 있고 본인 reviewer_id 매칭 건만 반환
- Reviewer 행이 없으면 빈 결과 (assigned_reviewer_name만 있어도 보이지 않음)
"""

from datetime import date, timedelta

from models.review_stage import PhaseType, ReviewStage
from models.user import UserRole


def test_my_reviews_returns_only_own_buildings(
    client, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    own = make_building(reviewer_id=reviewer_a.id, mgmt_no="MY-OWN-001")
    make_building(reviewer_id=reviewer_b.id, mgmt_no="MY-OTHER-001")

    res = client.get("/api/buildings/my-reviews", headers=headers_a)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"][0]["mgmt_no"] == own.mgmt_no


def test_my_reviews_supports_server_sorting(
    client, db_session, make_reviewer, make_building
):
    _, reviewer, headers = make_reviewer()
    b1 = make_building(reviewer_id=reviewer.id, mgmt_no="SORT-001")
    b2 = make_building(reviewer_id=reviewer.id, mgmt_no="SORT-003")
    b3 = make_building(reviewer_id=reviewer.id, mgmt_no="SORT-002")
    b1.gross_area = 100
    b2.gross_area = 300
    b3.gross_area = 200
    db_session.commit()

    default_res = client.get("/api/buildings/my-reviews", headers=headers)
    assert default_res.status_code == 200
    assert [item["mgmt_no"] for item in default_res.json()["items"]] == [
        "SORT-001",
        "SORT-002",
        "SORT-003",
    ]

    sorted_res = client.get(
        "/api/buildings/my-reviews",
        headers=headers,
        params={"sort_by": "gross_area", "sort_order": "desc"},
    )
    assert sorted_res.status_code == 200
    assert [item["mgmt_no"] for item in sorted_res.json()["items"]] == [
        "SORT-003",
        "SORT-002",
        "SORT-001",
    ]


def test_my_reviews_ignores_assigned_reviewer_name_match(
    client, db_session, make_user, make_building
):
    """Reviewer 행이 없는 사용자는 assigned_reviewer_name이 일치해도 빈 결과."""
    user, headers = make_user(UserRole.REVIEWER, name="홍길동")
    # 같은 이름이 assigned_reviewer_name에 들어있지만 reviewer_id는 없음
    from models.building import Building

    b = Building(
        mgmt_no="NAME-MATCH-001",
        assigned_reviewer_name="홍길동",
        reviewer_id=None,
    )
    db_session.add(b)
    db_session.commit()

    res = client.get("/api/buildings/my-reviews", headers=headers)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 0


def test_my_stats_returns_zero_when_no_reviewer_row(
    client, db_session, make_user
):
    user, headers = make_user(UserRole.REVIEWER, name="이순신")
    from models.building import Building

    b = Building(mgmt_no="STATS-NAME-001", assigned_reviewer_name="이순신")
    db_session.add(b)
    db_session.commit()

    res = client.get("/api/buildings/my-stats", headers=headers)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 0
    assert payload["need_review"] == 0


def test_my_stats_counts_only_own_reviewer_id(
    client, db_session, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    b1 = make_building(reviewer_id=reviewer_a.id)
    b2 = make_building(reviewer_id=reviewer_a.id)
    b3 = make_building(reviewer_id=reviewer_b.id)
    b1.gross_area = 1000
    b1.is_special_structure = True
    b1.current_phase = "doc_received"
    b1.final_result = "pass"
    b2.gross_area = 500
    b2.final_result = "fail"
    b3.gross_area = 9999
    b3.is_high_rise = True
    db_session.add_all([
        ReviewStage(
            building_id=b1.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            report_submitted_at=date.today(),
        ),
        ReviewStage(
            building_id=b2.id,
            phase=PhaseType.SUPPLEMENT_1,
            phase_order=1,
            report_submitted_at=date.today(),
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings/my-stats", headers=headers_a)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 2
    assert payload["total_area"] == 1500
    assert payload["area_over_1000"] == 1
    assert payload["high_risk"] == 1
    assert payload["need_review"] == 1
    assert payload["submitted_preliminary"] == 1
    assert payload["submitted_supplement"] == 1
    assert payload["submitted"] == 2
    assert payload["final_counts"]["pass"] == 1
    assert payload["final_counts"]["fail"] == 1


def test_my_stats_schedule_excludes_assigned_pending_stage(
    client, db_session, make_reviewer, make_building
):
    """배정완료로 되돌린 건물의 과거 미제출 예정일은 미제출 일정에서 제외한다."""
    _, reviewer, headers = make_reviewer()
    due = date.today() + timedelta(days=3)
    received = make_building(reviewer_id=reviewer.id, mgmt_no="MY-SCH-RECEIVED")
    received.current_phase = "doc_received"
    assigned = make_building(reviewer_id=reviewer.id, mgmt_no="MY-SCH-ASSIGNED")
    assigned.current_phase = "assigned"
    db_session.add_all([
        ReviewStage(
            building_id=received.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            report_due_date=due,
        ),
        ReviewStage(
            building_id=assigned.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            report_due_date=due,
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings/my-stats", headers=headers)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 2
    assert payload["need_review"] == 1
    assert payload["schedule_counts"]["in_progress"] == 1
    assert payload["schedule_counts"]["d_minus_3"] == 1
