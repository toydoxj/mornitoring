"""reviews 라우터 권한 회귀 테스트.

REVIEWER가 본인 담당 외 건물의 stages/inquiries/download에 접근하지 못함을 검증.
"""

from datetime import date

from models.review_stage import PhaseType, ReviewStage


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
