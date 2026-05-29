"""검토서 상세의견 통계 저장 회귀 테스트."""

from models.review_opinion_detail import ReviewOpinionDetail
from models.review_severity_summary import ReviewSeveritySummary
from models.review_stage import PhaseType, ReviewStage
from routers.reviews import _apply_opinion_details, _apply_severity_summaries


def test_apply_severity_summaries_replaces_existing_rows(db_session, make_building):
    building = make_building(mgmt_no="SEV-SUM-001")
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)

    _apply_severity_summaries(db_session, stage, {
        "category_severity_counts": [
            {
                "category": "부재설계의 적정성 - 구조설계 요소",
                "severity": "L2",
                "count": 1,
            },
            {
                "category": "부재설계의 적정성 - 구조설계 요소",
                "severity": "L3",
                "count": 2,
            },
            {"category": "기타의견", "severity": "L0", "count": 1},
        ],
    })
    db_session.commit()

    rows = (
        db_session.query(ReviewSeveritySummary)
        .filter(ReviewSeveritySummary.stage_id == stage.id)
        .order_by(
            ReviewSeveritySummary.category,
            ReviewSeveritySummary.severity,
        )
        .all()
    )
    assert [(row.category, row.severity, row.count) for row in rows] == [
        ("기타의견", "L0", 1),
        ("부재설계의 적정성 - 구조설계 요소", "L2", 1),
        ("부재설계의 적정성 - 구조설계 요소", "L3", 2),
    ]

    _apply_severity_summaries(db_session, stage, {
        "category_severity_counts": [
            {"category": "기타의견", "severity": "L4", "count": 1},
        ],
    })
    db_session.commit()

    refreshed_rows = (
        db_session.query(ReviewSeveritySummary)
        .filter(ReviewSeveritySummary.stage_id == stage.id)
        .all()
    )
    assert [(row.category, row.severity, row.count) for row in refreshed_rows] == [
        ("기타의견", "L4", 1),
    ]


def test_apply_opinion_details_replaces_existing_rows_and_phase_group(
    db_session,
    make_building,
):
    building = make_building(mgmt_no="OPN-DETAIL-001")
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.SUPPLEMENT_1,
        phase_order=1,
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)

    _apply_opinion_details(db_session, stage, "supplement_1", {
        "opinion_entries": [
            {
                "row": 33,
                "category": "부재설계의 적정성 - 구조설계 요소",
                "severity": "L3",
                "content": "전이보 스트럽 간격 보완할 것.",
            },
            {
                "row": 78,
                "category": "기타의견",
                "severity": "L0",
                "content": "지반조사서 누락",
            },
        ],
    })
    db_session.commit()

    rows = (
        db_session.query(ReviewOpinionDetail)
        .filter(ReviewOpinionDetail.stage_id == stage.id)
        .order_by(ReviewOpinionDetail.row_number)
        .all()
    )
    assert [
        (row.phase, row.phase_group, row.row_number, row.severity, row.content)
        for row in rows
    ] == [
        ("supplement_1", "supplement", 33, "L3", "전이보 스트럽 간격 보완할 것."),
        ("supplement_1", "supplement", 78, "L0", "지반조사서 누락"),
    ]

    _apply_opinion_details(db_session, stage, "supplement_1", {
        "opinion_entries": [
            {
                "row": 40,
                "category": "기타의견",
                "severity": "L4",
                "content": "구조계산서 누락",
            },
        ],
    })
    db_session.commit()

    refreshed_rows = (
        db_session.query(ReviewOpinionDetail)
        .filter(ReviewOpinionDetail.stage_id == stage.id)
        .all()
    )
    assert [
        (row.category, row.severity, row.content)
        for row in refreshed_rows
    ] == [("기타의견", "L4", "구조계산서 누락")]
