"""reviews 라우터 권한 회귀 테스트.

REVIEWER가 본인 담당 외 건물의 stages/inquiries/download에 접근하지 못함을 검증.
"""

from datetime import date

from models.review_opinion_detail import ReviewOpinionDetail
from models.review_severity_summary import ReviewSeveritySummary
from models.review_stage import PhaseType, ReviewStage
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


def test_chief_secretary_can_delete_review_opinion_and_related_rows(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    building = make_building(mgmt_no="DELETE-OPINION-001")
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        review_opinion="삭제할 검토의견",
        severity_l2_count=1,
        severity_l4_count=1,
    )
    db_session.add(stage)
    db_session.flush()
    db_session.add(ReviewOpinionDetail(
        stage_id=stage.id,
        phase=PhaseType.PRELIMINARY.value,
        phase_group="preliminary",
        row_number=1,
        category="구조계산서",
        severity="L4",
        content="상세 검토의견",
    ))
    db_session.add(ReviewSeveritySummary(
        stage_id=stage.id,
        category="구조계산서",
        severity="L4",
        count=1,
    ))
    db_session.commit()

    res = client.delete(f"/api/reviews/stages/{stage.id}/opinion", headers=headers)

    assert res.status_code == 200
    payload = res.json()
    assert payload["review_opinion"] is None
    assert payload["severity_l2_count"] == 0
    assert payload["severity_l4_count"] == 0

    db_session.refresh(stage)
    assert stage.review_opinion is None
    assert stage.severity_l2_count == 0
    assert stage.severity_l4_count == 0
    assert (
        db_session.query(ReviewOpinionDetail)
        .filter(ReviewOpinionDetail.stage_id == stage.id)
        .count()
        == 0
    )
    assert (
        db_session.query(ReviewSeveritySummary)
        .filter(ReviewSeveritySummary.stage_id == stage.id)
        .count()
        == 0
    )
