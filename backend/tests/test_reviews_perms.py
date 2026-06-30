"""reviews 라우터 권한 회귀 테스트.

REVIEWER가 본인 담당 외 건물의 stages/inquiries/download에 접근하지 못함을 검증.
"""

from datetime import date

from models.inappropriate_note import InappropriateNote
from models.review_opinion_detail import ReviewOpinionDetail
from models.review_severity_summary import ReviewSeveritySummary
from models.review_stage import PhaseType, ResultType, ReviewStage
from models.user import UserRole


def _make_stage(db, building_id: int, *, s3_key: str | None = None) -> ReviewStage:
    stage = ReviewStage(
        building_id=building_id,
        phase=PhaseType.PRELIMINARY,
        phase_order=1,
        doc_received_at=date.today(),
        s3_file_key=s3_key,
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return stage


def test_reviewer_cannot_get_stages_of_other_building(
    client, db_session, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    other = make_building(reviewer_id=reviewer_b.id, mgmt_no="OTHER-STAGE-001")
    _make_stage(db_session, other.id)

    res = client.get(f"/api/reviews/stages/{other.id}", headers=headers_a)
    assert res.status_code == 404


def test_reviewer_cannot_get_building_inquiries_of_other_building(
    client, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    other = make_building(reviewer_id=reviewer_b.id, mgmt_no="OTHER-INQ-001")

    res = client.get(f"/api/reviews/building-inquiries/{other.mgmt_no}", headers=headers_a)
    assert res.status_code == 404


def test_reviewer_cannot_download_other_building_stage(
    client, db_session, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    other = make_building(reviewer_id=reviewer_b.id, mgmt_no="OTHER-DL-001")
    stage = _make_stage(db_session, other.id, s3_key="reviews/preliminary/test.pdf")

    res = client.get(f"/api/reviews/download/{stage.id}", headers=headers_a)
    assert res.status_code == 404


def test_reviewer_can_get_stages_of_own_building(
    client, db_session, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    own = make_building(reviewer_id=reviewer_a.id, mgmt_no="OWN-STAGE-001")
    _make_stage(db_session, own.id)

    res = client.get(f"/api/reviews/stages/{own.id}", headers=headers_a)
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["building_id"] == own.id


def test_chief_secretary_can_delete_review_stage_history_and_related_rows(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    building = make_building(mgmt_no="DELETE-STAGE-001")
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        review_opinion="review opinion to delete",
        severity_l2_count=1,
        severity_l4_count=1,
    )
    db_session.add(stage)
    db_session.flush()
    db_session.add(InappropriateNote(
        stage_id=stage.id,
        author_id=1,
        author_name="secretary",
        content="note to delete",
    ))
    db_session.add(ReviewOpinionDetail(
        stage_id=stage.id,
        phase=PhaseType.PRELIMINARY.value,
        phase_group="preliminary",
        row_number=1,
        category="structure",
        severity="L4",
        content="detail opinion",
    ))
    db_session.add(ReviewSeveritySummary(
        stage_id=stage.id,
        category="structure",
        severity="L4",
        count=1,
    ))
    db_session.commit()
    stage_id = stage.id

    res = client.delete(f"/api/reviews/stages/{stage_id}", headers=headers)

    assert res.status_code == 200
    payload = res.json()
    assert payload["stage_id"] == stage_id
    assert payload["building_id"] == building.id

    db_session.expire_all()
    assert db_session.get(ReviewStage, stage_id) is None
    assert (
        db_session.query(InappropriateNote)
        .filter(InappropriateNote.stage_id == stage_id)
        .count()
        == 0
    )
    assert (
        db_session.query(ReviewOpinionDetail)
        .filter(ReviewOpinionDetail.stage_id == stage_id)
        .count()
        == 0
    )
    assert (
        db_session.query(ReviewSeveritySummary)
        .filter(ReviewSeveritySummary.stage_id == stage_id)
        .count()
        == 0
    )


def test_struct_engineer_firm_list_groups_related_numbers_and_reviewers(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _, reviewer, _ = make_reviewer()
    first = make_building(reviewer_id=reviewer.id, mgmt_no="SE-FIRM-001")
    second = make_building(reviewer_id=reviewer.id, mgmt_no="SE-FIRM-002")
    ignored = make_building(mgmt_no="SE-FIRM-003")
    first.struct_eng_firm = "한빛구조기술사사무소"
    first.struct_eng_name = "홍구조"
    second.struct_eng_firm = " 한빛구조기술사사무소 "
    second.struct_eng_name = "김구조"
    ignored.struct_eng_firm = ""
    db_session.add(
        ReviewStage(
            building_id=first.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            report_submitted_at=date(2026, 6, 30),
            reviewer_name="검토위원1",
            result=ResultType.PASS,
        )
    )
    db_session.commit()

    res = client.get("/api/reviews/struct-engineer-firms", headers=headers)

    assert res.status_code == 200
    payload = res.json()
    assert len(payload) == 1
    group = payload[0]
    assert group["firm"] == "한빛구조기술사사무소"
    assert group["building_count"] == 2
    assert group["reviewer_count"] == 1
    assert group["submitted_count"] == 1
    assert [item["mgmt_no"] for item in group["items"]] == [
        "SE-FIRM-001",
        "SE-FIRM-002",
    ]
    assert group["items"][0]["latest_phase"] == "preliminary"
    assert group["items"][0]["latest_report_submitted_at"] == "2026-06-30"


def test_reviewer_cannot_access_struct_engineer_firm_list(client, make_reviewer):
    _, _, headers = make_reviewer()

    res = client.get("/api/reviews/struct-engineer-firms", headers=headers)

    assert res.status_code == 403


def test_structural_engineer_drawing_creator_list_groups_related_numbers(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _, reviewer, _ = make_reviewer()
    first = make_building(reviewer_id=reviewer.id, mgmt_no="DRAW-SE-001")
    second = make_building(reviewer_id=reviewer.id, mgmt_no="DRAW-SE-002")
    ignored = make_building(reviewer_id=reviewer.id, mgmt_no="DRAW-SE-003")
    first.struct_eng_firm = "한빛구조기술사사무소"
    first.drawing_creator_firm = "한빛구조도면사무소"
    first.drawing_creator_name = "이도면"
    first.drawing_creator_qualification = "건축구조기술사"
    second.struct_eng_firm = " 한빛구조기술사사무소 "
    second.drawing_creator_firm = " 한빛구조도면사무소 "
    second.drawing_creator_name = "박도면"
    second.drawing_creator_qualification = "구조기술사"
    ignored.struct_eng_firm = "무시구조기술사사무소"
    ignored.drawing_creator_firm = "한빛구조도면사무소"
    ignored.drawing_creator_name = "최건축"
    ignored.drawing_creator_qualification = "건축사"
    db_session.add(
        ReviewStage(
            building_id=first.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            report_submitted_at=date(2026, 6, 30),
            reviewer_name="검토위원1",
            result=ResultType.PASS,
        )
    )
    db_session.commit()

    res = client.get("/api/reviews/structural-engineer-drawing-creators", headers=headers)

    assert res.status_code == 200
    payload = res.json()
    assert len(payload) == 1
    group = payload[0]
    assert group["firm"] == "한빛구조기술사사무소"
    assert group["building_count"] == 2
    assert group["reviewer_count"] == 1
    assert group["submitted_count"] == 1
    assert [item["mgmt_no"] for item in group["items"]] == [
        "DRAW-SE-001",
        "DRAW-SE-002",
    ]
    assert group["items"][0]["struct_eng_firm"] == "한빛구조기술사사무소"
    assert group["items"][0]["drawing_creator_name"] == "이도면"
    assert group["items"][0]["latest_phase"] == "preliminary"


def test_reviewer_cannot_access_structural_engineer_drawing_creator_list(
    client, make_reviewer
):
    _, _, headers = make_reviewer()

    res = client.get("/api/reviews/structural-engineer-drawing-creators", headers=headers)

    assert res.status_code == 403
