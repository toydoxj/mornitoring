"""buildings 라우터 권한 회귀 테스트.

- /stats, /reviewer-names: REVIEWER 차단 (관리자 전용)
- GET /: REVIEWER는 본인 reviewer_id 매칭 건만 반환
- GET /{id}: REVIEWER는 본인 담당이 아니면 404
"""

from datetime import date

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


def test_building_list_supports_header_sort_fields(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    b1 = make_building(mgmt_no="HEADER-SORT-001")
    b2 = make_building(mgmt_no="HEADER-SORT-002")
    b1.sido = "서울특별시"
    b1.sigungu = "강남구"
    b1.beopjeongdong = "대치동"
    b2.sido = "강원특별자치도"
    b2.sigungu = "춘천시"
    b2.beopjeongdong = "퇴계동"
    db_session.add_all([
        ReviewStage(
            building_id=b1.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            result=ResultType.PASS,
        ),
        ReviewStage(
            building_id=b2.id,
            phase=PhaseType.SUPPLEMENT_1,
            phase_order=1,
            result=ResultType.RECALCULATE,
        ),
    ])
    db_session.commit()

    address_res = client.get(
        "/api/buildings",
        headers=headers,
        params={"sort_by": "address", "sort_order": "asc"},
    )
    assert address_res.status_code == 200
    assert [item["mgmt_no"] for item in address_res.json()["items"][:2]] == [
        "HEADER-SORT-002",
        "HEADER-SORT-001",
    ]

    latest_res = client.get(
        "/api/buildings",
        headers=headers,
        params={"sort_by": "latest_result", "sort_order": "desc"},
    )
    assert latest_res.status_code == 200
    assert [item["mgmt_no"] for item in latest_res.json()["items"][:2]] == [
        "HEADER-SORT-002",
        "HEADER-SORT-001",
    ]


def test_building_list_returns_and_sorts_current_report_due_date(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    early = make_building(mgmt_no="DUE-SORT-001")
    late = make_building(mgmt_no="DUE-SORT-002")
    without_due = make_building(mgmt_no="DUE-SORT-003")
    early.current_phase = "doc_received"
    late.current_phase = "doc_received"
    without_due.current_phase = "doc_received"
    db_session.add_all([
        ReviewStage(
            building_id=early.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            report_due_date=date(2026, 7, 10),
        ),
        ReviewStage(
            building_id=late.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            report_due_date=date(2026, 7, 20),
        ),
        ReviewStage(
            building_id=early.id,
            phase=PhaseType.SUPPLEMENT_1,
            phase_order=1,
            report_due_date=date(2026, 8, 1),
        ),
    ])
    db_session.commit()

    res = client.get(
        "/api/buildings",
        headers=headers,
        params={"sort_by": "report_due_date", "sort_order": "asc"},
    )
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["mgmt_no"] for item in items[:3]] == [
        "DUE-SORT-001",
        "DUE-SORT-002",
        "DUE-SORT-003",
    ]
    early_item = next(item for item in items if item["mgmt_no"] == "DUE-SORT-001")
    assert early_item["report_due_date"] == "2026-07-10"


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


def test_chief_secretary_can_bulk_finalize_selected_pass_buildings(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    preliminary_pass = make_building(mgmt_no="BULK-FINAL-PRE-001")
    preliminary_pass.current_phase = "preliminary"
    supplement_pass = make_building(mgmt_no="BULK-FINAL-SUP-001")
    supplement_pass.current_phase = "supplement_1"
    recalculate = make_building(mgmt_no="BULK-FINAL-SKIP-001")
    recalculate.current_phase = "preliminary"
    db_session.add_all([
        ReviewStage(
            building_id=preliminary_pass.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            result=ResultType.PASS,
        ),
        ReviewStage(
            building_id=supplement_pass.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            result=ResultType.RECALCULATE,
        ),
        ReviewStage(
            building_id=supplement_pass.id,
            phase=PhaseType.SUPPLEMENT_1,
            phase_order=1,
            result=ResultType.PASS,
        ),
        ReviewStage(
            building_id=recalculate.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            result=ResultType.RECALCULATE,
        ),
    ])
    db_session.commit()

    res = client.post(
        "/api/buildings/finalize-pass/bulk",
        headers=headers,
        json={
            "building_ids": [
                preliminary_pass.id,
                supplement_pass.id,
                recalculate.id,
            ],
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["applied"] == 2
    assert body["skipped"] == 1
    by_mgmt_no = {item["mgmt_no"]: item for item in body["items"]}
    assert by_mgmt_no["BULK-FINAL-PRE-001"]["final_result"] == "pass"
    assert by_mgmt_no["BULK-FINAL-SUP-001"]["final_result"] == "pass_supplement"
    assert by_mgmt_no["BULK-FINAL-SKIP-001"]["status"] == "skipped"

    db_session.refresh(preliminary_pass)
    db_session.refresh(supplement_pass)
    db_session.refresh(recalculate)
    assert preliminary_pass.final_result == "pass"
    assert preliminary_pass.current_phase == "completed"
    assert supplement_pass.final_result == "pass_supplement"
    assert supplement_pass.current_phase == "completed"
    assert recalculate.final_result is None
    assert recalculate.current_phase == "preliminary"


def test_only_chief_secretary_can_bulk_finalize_pass(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.TEAM_LEADER)
    building = make_building(mgmt_no="BULK-FINAL-FORBIDDEN-001")
    building.current_phase = "preliminary"
    db_session.add(ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        result=ResultType.PASS,
    ))
    db_session.commit()

    res = client.post(
        "/api/buildings/finalize-pass/bulk",
        headers=headers,
        json={"building_ids": [building.id]},
    )
    assert res.status_code == 403
