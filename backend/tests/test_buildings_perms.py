"""buildings 라우터 권한 회귀 테스트.

- /stats, /reviewer-names: REVIEWER 차단 (관리자 전용)
- GET /: REVIEWER는 본인 reviewer_id 매칭 건만 반환
- GET /{id}: REVIEWER는 본인 담당이 아니면 404
"""

from models.review_stage import PhaseType, ResultType, ReviewStage
from models.user import UserRole


def test_reviewer_cannot_access_stats(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.get("/api/buildings/stats", headers=headers)
    assert res.status_code == 403


def test_reviewer_cannot_access_reviewer_names(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.get("/api/buildings/reviewer-names", headers=headers)
    assert res.status_code == 403


def test_reviewer_list_only_own_buildings(
    client, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    own_a = make_building(reviewer_id=reviewer_a.id, mgmt_no="OWN-A-001")
    make_building(reviewer_id=reviewer_b.id, mgmt_no="OWN-B-001")
    make_building(reviewer_id=None, mgmt_no="UNASSIGNED-001")

    res = client.get("/api/buildings", headers=headers_a)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["mgmt_no"] == own_a.mgmt_no


def test_reviewer_get_other_building_returns_404(
    client, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    other = make_building(reviewer_id=reviewer_b.id, mgmt_no="OTHER-001")

    res = client.get(f"/api/buildings/{other.id}", headers=headers_a)
    assert res.status_code == 404


def test_secretary_can_access_stats(client, make_user):
    _, headers = make_user(UserRole.SECRETARY)
    res = client.get("/api/buildings/stats", headers=headers)
    assert res.status_code == 200


def test_chief_secretary_can_finalize_preliminary_pass(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    building = make_building(mgmt_no="FINAL-PRE-001")
    building.current_phase = "preliminary"
    db_session.add(ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        result=ResultType.PASS,
    ))
    db_session.commit()

    res = client.post(f"/api/buildings/{building.id}/finalize-pass", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["final_result"] == "pass"
    assert body["current_phase"] == "completed"


def test_chief_secretary_can_finalize_supplement_pass(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    building = make_building(mgmt_no="FINAL-SUP-001")
    building.current_phase = "supplement_1"
    db_session.add_all([
        ReviewStage(
            building_id=building.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            result=ResultType.RECALCULATE,
        ),
        ReviewStage(
            building_id=building.id,
            phase=PhaseType.SUPPLEMENT_1,
            phase_order=1,
            result=ResultType.PASS,
        ),
    ])
    db_session.commit()

    res = client.post(f"/api/buildings/{building.id}/finalize-pass", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["final_result"] == "pass_supplement"
    assert body["current_phase"] == "completed"


def test_only_chief_secretary_can_finalize_pass(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.TEAM_LEADER)
    building = make_building(mgmt_no="FINAL-FORBIDDEN-001")
    building.current_phase = "preliminary"
    db_session.add(ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        result=ResultType.PASS,
    ))
    db_session.commit()

    res = client.post(f"/api/buildings/{building.id}/finalize-pass", headers=headers)
    assert res.status_code == 403
