"""검토서 분류별 심각도 집계 저장 회귀 테스트."""

from models.review_severity_summary import ReviewSeveritySummary
from models.review_stage import PhaseType, ReviewStage
from routers.reviews import _apply_severity_summaries


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
