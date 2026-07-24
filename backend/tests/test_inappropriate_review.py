"""부적합 대상 검토 화면 정책 테스트.

- 조 구분 없이 간사진 전체가 같은 목록을 본다.
- 목록에 조/검토위원이 함께 나온다.
- 확정(심각)보다 상위 단계인 '붕괴우려'(collapse_risk) 판정을 지원한다.
"""

from models.review_stage import InappropriateDecision, PhaseType, ReviewStage
from models.user import UserRole


def _make_inappropriate_stage(db_session, building, reviewer_name="검토자", result=None):
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        reviewer_name=reviewer_name,
        result=result,
        inappropriate_review_needed=True,
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)
    return stage


def test_inappropriate_list_exposes_group_and_reviewer(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()

    rev_user, reviewer, _ = make_reviewer()
    rev_user.name = "3조위원"
    reviewer.group_no = 3
    db_session.commit()

    building = make_building(mgmt_no="INAP-G3", reviewer_id=reviewer.id)
    _make_inappropriate_stage(db_session, building, reviewer_name="실제검토자")

    res = client.get("/api/reviews/inappropriate", headers=sec_h)
    assert res.status_code == 200
    item = next(i for i in res.json()["items"] if i["mgmt_no"] == "INAP-G3")
    assert item["group_no"] == 3
    assert item["reviewer_name"] == "실제검토자"


def test_inappropriate_list_falls_back_to_assigned_reviewer_name(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer()
    rev_user.name = "배정위원"
    reviewer.group_no = 2
    db_session.commit()

    building = make_building(mgmt_no="INAP-FALLBACK", reviewer_id=reviewer.id)
    _make_inappropriate_stage(db_session, building, reviewer_name=None)

    res = client.get("/api/reviews/inappropriate", headers=headers)
    assert res.status_code == 200
    item = next(i for i in res.json()["items"] if i["mgmt_no"] == "INAP-FALLBACK")
    assert item["group_no"] == 2
    assert item["reviewer_name"] == "배정위원"


def test_secretary_can_set_collapse_risk_decision(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()

    rev_user, reviewer, _ = make_reviewer()
    reviewer.group_no = 5
    db_session.commit()

    building = make_building(mgmt_no="INAP-COLLAPSE", reviewer_id=reviewer.id)
    stage = _make_inappropriate_stage(db_session, building)

    res = client.patch(
        f"/api/reviews/inappropriate/{stage.id}",
        headers=sec_h,
        json={"decision": "collapse_risk"},
    )
    assert res.status_code == 200
    assert res.json()["decision"] == "collapse_risk"

    db_session.refresh(stage)
    assert stage.inappropriate_decision == InappropriateDecision.COLLAPSE_RISK


def test_inappropriate_list_filters_by_collapse_risk(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer()
    reviewer.group_no = 4
    db_session.commit()

    risky = make_building(mgmt_no="INAP-RISK", reviewer_id=reviewer.id)
    plain = make_building(mgmt_no="INAP-PLAIN", reviewer_id=reviewer.id)
    risky_stage = _make_inappropriate_stage(db_session, risky)
    _make_inappropriate_stage(db_session, plain)
    risky_stage.inappropriate_decision = InappropriateDecision.COLLAPSE_RISK
    db_session.commit()

    res = client.get(
        "/api/reviews/inappropriate",
        params={"decision": "collapse_risk"},
        headers=headers,
    )
    assert res.status_code == 200
    mgmts = {item["mgmt_no"] for item in res.json()["items"]}
    assert mgmts == {"INAP-RISK"}

    pending = client.get(
        "/api/reviews/inappropriate",
        params={"decision": "pending"},
        headers=headers,
    )
    assert pending.status_code == 200
    assert {item["mgmt_no"] for item in pending.json()["items"]} == {"INAP-PLAIN"}


def test_inappropriate_rejects_unknown_decision(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _, reviewer, _ = make_reviewer()
    reviewer.group_no = 1
    db_session.commit()
    building = make_building(mgmt_no="INAP-BAD", reviewer_id=reviewer.id)
    stage = _make_inappropriate_stage(db_session, building)

    res = client.patch(
        f"/api/reviews/inappropriate/{stage.id}",
        headers=headers,
        json={"decision": "collapse"},
    )
    assert res.status_code == 400
