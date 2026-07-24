"""통계자료 화면 전용 정책 회귀 테스트.

- 통계자료(scope=all)는 간사도 조 구분 없이 전체를 본다.
- 대시보드(scope 미지정)는 기존대로 조별 집계를 유지한다.
- 의견 심각도 지정 화면은 조 구분 없이 조회/수정하고,
  부적합 검토 체크는 검토 단계(stage) 단위로 부적합 목록에 반영된다.
"""

from models.review_opinion_detail import ReviewOpinionDetail
from models.review_stage import PhaseType, ReviewStage
from models.user import UserRole


def _two_group_buildings(make_reviewer, make_building, db_session):
    """1조/2조 검토위원과 각 조 건물 1개씩."""
    rev1_user, rev1, _ = make_reviewer()
    rev1_user.name = "1조위원"
    rev1.group_no = 1
    rev1.specialty = "RC구조"
    rev2_user, rev2, _ = make_reviewer()
    rev2_user.name = "2조위원"
    rev2.group_no = 2
    db_session.commit()

    b1 = make_building(mgmt_no="STAT-G1", reviewer_id=rev1.id)
    b2 = make_building(mgmt_no="STAT-G2", reviewer_id=rev2.id)
    return rev1, b1, rev2, b2


def _make_opinion(db_session, building, content="전이보 스트럽 보완 필요", severity="L0"):
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        reviewer_name="검토자",
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)

    detail = ReviewOpinionDetail(
        stage_id=stage.id,
        phase="preliminary",
        phase_group="preliminary",
        row_number=33,
        category="기타의견",
        severity=severity,
        content=content,
    )
    db_session.add(detail)
    db_session.commit()
    db_session.refresh(detail)
    return stage, detail


# ===== 통계자료 집계 범위 (/api/buildings/stats?scope=all) =====

def test_secretary_stats_scope_all_includes_other_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _two_group_buildings(make_reviewer, make_building, db_session)

    res = client.get("/api/buildings/stats", params={"scope": "all"}, headers=sec_h)
    assert res.status_code == 200
    assert res.json()["total"] == 2


def test_secretary_stats_without_scope_stays_group_scoped(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _two_group_buildings(make_reviewer, make_building, db_session)

    res = client.get("/api/buildings/stats", headers=sec_h)
    assert res.status_code == 200
    assert res.json()["total"] == 1


def test_stats_rejects_unknown_scope(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.get("/api/buildings/stats", params={"scope": "group"}, headers=headers)
    assert res.status_code == 400


# ===== 의견 심각도 지정 (/api/reviews/opinion-details) =====

def test_secretary_opinion_details_include_other_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, b1, _, b2 = _two_group_buildings(make_reviewer, make_building, db_session)
    _make_opinion(db_session, b1, content="1조 의견")
    _make_opinion(db_session, b2, content="2조 의견")

    res = client.get("/api/reviews/opinion-details", headers=sec_h)
    assert res.status_code == 200
    items = res.json()["items"]
    by_mgmt = {item["mgmt_no"]: item for item in items}
    assert {"STAT-G1", "STAT-G2"}.issubset(set(by_mgmt))
    assert by_mgmt["STAT-G2"]["group_no"] == 2
    assert by_mgmt["STAT-G2"]["reviewer_name"] == "검토자"
    assert by_mgmt["STAT-G2"]["inappropriate_review_needed"] is False


def test_secretary_can_update_other_group_opinion_severity(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, _, _, b2 = _two_group_buildings(make_reviewer, make_building, db_session)
    _, detail = _make_opinion(db_session, b2)

    res = client.patch(
        f"/api/reviews/opinion-details/{detail.id}/severity",
        headers=sec_h,
        json={"severity": "L3"},
    )
    assert res.status_code == 200
    assert res.json()["severity"] == "L3"

    db_session.refresh(detail)
    assert detail.severity == "L3"


# ===== 부적합 검토 체크 (/api/reviews/opinion-details/{id}/inappropriate) =====

def test_opinion_inappropriate_check_adds_stage_to_inappropriate_list(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, chief_h = make_user(UserRole.CHIEF_SECRETARY)
    _, _, _, b2 = _two_group_buildings(make_reviewer, make_building, db_session)
    stage, detail = _make_opinion(db_session, b2)

    before = client.get("/api/reviews/inappropriate", headers=chief_h)
    assert before.status_code == 200
    assert "STAT-G2" not in [item["mgmt_no"] for item in before.json()["items"]]

    # 통계자료 화면이므로 1조 간사가 2조 건의 체크도 할 수 있다.
    checked = client.patch(
        f"/api/reviews/opinion-details/{detail.id}/inappropriate",
        headers=sec_h,
        json={"inappropriate_review_needed": True},
    )
    assert checked.status_code == 200
    assert checked.json()["inappropriate_review_needed"] is True

    db_session.refresh(stage)
    assert stage.inappropriate_review_needed is True

    after = client.get("/api/reviews/inappropriate", headers=chief_h)
    assert after.status_code == 200
    assert "STAT-G2" in [item["mgmt_no"] for item in after.json()["items"]]

    # 부적합 검토 목록도 조 구분 없이 노출되므로 1조 간사에게도 보인다.
    sec_list = client.get("/api/reviews/inappropriate", headers=sec_h)
    assert sec_list.status_code == 200
    assert "STAT-G2" in [item["mgmt_no"] for item in sec_list.json()["items"]]


def test_opinion_inappropriate_uncheck_removes_stage_from_list(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _, b1, _, _ = _two_group_buildings(make_reviewer, make_building, db_session)
    stage, detail = _make_opinion(db_session, b1)
    stage.inappropriate_review_needed = True
    db_session.commit()

    res = client.patch(
        f"/api/reviews/opinion-details/{detail.id}/inappropriate",
        headers=headers,
        json={"inappropriate_review_needed": False},
    )
    assert res.status_code == 200
    assert res.json()["inappropriate_review_needed"] is False

    db_session.refresh(stage)
    assert stage.inappropriate_review_needed is False
    assert stage.inappropriate_decision is None

    after = client.get("/api/reviews/inappropriate", headers=headers)
    assert "STAT-G1" not in [item["mgmt_no"] for item in after.json()["items"]]


# ===== 통계 팝업용 건축물 요약 (/api/buildings/{id}/summary) =====

def test_building_summary_available_for_other_group_with_reviewer_roster(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, _, rev2, b2 = _two_group_buildings(make_reviewer, make_building, db_session)

    # 같은 2조에 위원 1명 추가 — 명단에 함께 나와야 한다.
    mate_user, mate, _ = make_reviewer()
    mate_user.name = "2조동료"
    mate.group_no = 2
    db_session.commit()

    _make_opinion(db_session, b2)

    res = client.get(f"/api/buildings/{b2.id}/summary", headers=sec_h)
    assert res.status_code == 200
    body = res.json()

    assert body["building"]["mgmt_no"] == "STAT-G2"
    assert body["group_no"] == 2
    assert body["reviewer_name"] == "2조위원"

    roster = {item["name"]: item for item in body["group_reviewers"]}
    assert {"2조위원", "2조동료"} == set(roster)
    assert roster["2조위원"]["is_assigned"] is True
    assert roster["2조위원"]["assigned_count"] == 1
    assert roster["2조동료"]["is_assigned"] is False
    assert roster["2조동료"]["assigned_count"] == 0
    assert rev2.id == roster["2조위원"]["reviewer_id"]

    assert len(body["stages"]) == 1
    assert body["stages"][0]["phase"] == "preliminary"


def test_building_summary_denied_for_reviewer(
    client, db_session, make_user, make_reviewer, make_building
):
    _, _, reviewer_headers = make_reviewer()
    _, b1, _, _ = _two_group_buildings(make_reviewer, make_building, db_session)

    res = client.get(f"/api/buildings/{b1.id}/summary", headers=reviewer_headers)
    assert res.status_code == 403
