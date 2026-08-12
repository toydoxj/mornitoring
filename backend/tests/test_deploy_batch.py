"""배포차수(관리번호 일련번호 구간) 판별 및 필터 테스트."""

import pytest

from engines.deploy_batch import deploy_batch_of, parse_mgmt_serial
from models.building import Building
from models.user import UserRole


@pytest.mark.parametrize(
    "mgmt_no,expected",
    [
        # 구간 경계값 — 시작/끝 모두 확인
        ("2025-0001", 1),
        ("2025-0262", 1),
        ("2025-0263", 2),
        ("2025-0362", 2),
        ("2025-0363", 3),
        ("2025-2668", 3),
        ("2025-2669", 4),
        ("2025-5046", 4),
        ("2025-5047", 5),
        ("2025-9999", 5),
        # 연도가 달라도 일련번호 구간만 본다
        ("2026-0262", 1),
        ("2026-2669", 4),
    ],
)
def test_배포차수_구간_판별(mgmt_no, expected):
    assert deploy_batch_of(mgmt_no) == expected


@pytest.mark.parametrize(
    "mgmt_no",
    [
        None,
        "",
        "2025-0000",        # 일련번호 0은 어느 구간에도 없음
        "QUAL-CHECK-001",   # 구분자 개수가 다름
        "2025-262",         # 제로패딩 4자리 아님
        "25-0262",          # 연도 4자리 아님
        "ANY-001",
    ],
)
def test_비정규_관리번호는_배포차수_없음(mgmt_no):
    assert deploy_batch_of(mgmt_no) is None


def test_일련번호_파싱():
    assert parse_mgmt_serial("2025-0262") == 262
    assert parse_mgmt_serial("2025-5047") == 5047
    assert parse_mgmt_serial("2025-00262") is None


def _make_buildings(db, mgmt_nos: list[str]) -> None:
    for mgmt_no in mgmt_nos:
        db.add(Building(mgmt_no=mgmt_no))
    db.commit()


def test_목록_배포차수_필터(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _make_buildings(
        db_session,
        ["2025-0100", "2025-0262", "2025-0263", "2025-1000", "2025-5047", "ODD-1"],
    )

    res = client.get("/api/buildings", params={"batch": 1}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    assert [item["mgmt_no"] for item in body["items"]] == ["2025-0100", "2025-0262"]
    assert {item["deploy_batch"] for item in body["items"]} == {1}

    res = client.get("/api/buildings", params={"batch": 2}, headers=headers)
    assert [item["mgmt_no"] for item in res.json()["items"]] == ["2025-0263"]

    res = client.get("/api/buildings", params={"batch": 5}, headers=headers)
    assert [item["mgmt_no"] for item in res.json()["items"]] == ["2025-5047"]


def test_목록_배포차수_필터_없으면_전체(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _make_buildings(db_session, ["2025-0100", "2025-3000", "ODD-1"])

    body = client.get("/api/buildings", headers=headers).json()
    assert body["total"] == 3
    batches = {item["mgmt_no"]: item["deploy_batch"] for item in body["items"]}
    assert batches == {"2025-0100": 1, "2025-3000": 4, "ODD-1": None}


def test_목록_허용되지_않는_배포차수는_400(client, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    res = client.get("/api/buildings", params={"batch": 9}, headers=headers)
    assert res.status_code == 400


def test_통계_배포차수_필터와_분포(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _make_buildings(
        db_session,
        ["2025-0100", "2025-0262", "2025-0300", "2025-3000", "ODD-1"],
    )

    body = client.get("/api/buildings/stats", headers=headers).json()
    assert body["total"] == 5
    # 분포는 배포차수 필터와 무관하게 항상 전체
    assert body["deploy_batch_counts"] == {
        "1": 2,
        "2": 1,
        "3": 0,
        "4": 1,
        "5": 0,
        "none": 1,
    }

    filtered = client.get(
        "/api/buildings/stats", params={"batch": 1}, headers=headers
    ).json()
    assert filtered["total"] == 2
    assert filtered["deploy_batch_counts"] == body["deploy_batch_counts"]


def test_통계_배포차수별_진행_현황(client, db_session, make_user, make_reviewer):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _, reviewer, _ = make_reviewer()

    # 1차수: 미배포 1건(배정됨) + 예비검토 1건(배정됨)
    db_session.add(Building(
        mgmt_no="2025-0100", reviewer_id=reviewer.id, current_phase="assigned"
    ))
    db_session.add(Building(
        mgmt_no="2025-0101", reviewer_id=reviewer.id, current_phase="doc_received"
    ))
    # 4차수: 보완검토 1건 + 최종완료 1건(미배정)
    db_session.add(Building(
        mgmt_no="2025-3000", reviewer_id=reviewer.id, current_phase="supplement_2"
    ))
    db_session.add(Building(
        mgmt_no="2025-3001", current_phase="completed", final_result="pass"
    ))
    db_session.commit()

    body = client.get("/api/buildings/stats", headers=headers).json()
    progress = {row["batch"]: row for row in body["deploy_batch_progress"]}
    # 1~5차수 + 미분류(None) 행이 항상 존재한다
    assert set(progress) == {1, 2, 3, 4, 5, None}

    assert progress[1] == {
        "batch": 1,
        "assigned": 2,
        "not_distributed": 1,
        "preliminary": 1,
        "supplement": 0,
        "completed": 0,
        "total": 2,
    }
    assert progress[4] == {
        "batch": 4,
        "assigned": 1,
        "not_distributed": 0,
        "preliminary": 0,
        "supplement": 1,
        "completed": 1,
        "total": 2,
    }
    assert progress[2]["total"] == 0

    # 배포차수 필터를 걸어도 차수별 분해는 전체를 유지한다
    filtered = client.get(
        "/api/buildings/stats", params={"batch": 1}, headers=headers
    ).json()
    assert filtered["total"] == 2
    assert filtered["deploy_batch_progress"] == body["deploy_batch_progress"]


def test_통계_허용되지_않는_배포차수는_400(client, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    res = client.get("/api/buildings/stats", params={"batch": 0}, headers=headers)
    assert res.status_code == 400


def test_의견_상세_목록_배포차수_필터(client, db_session, make_user, make_building):
    from models.review_opinion_detail import ReviewOpinionDetail
    from models.review_stage import PhaseType, ReviewStage

    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    for mgmt_no in ("2025-0100", "2025-3000"):
        building = make_building(mgmt_no=mgmt_no)
        stage = ReviewStage(
            building_id=building.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            reviewer_name="검토자",
        )
        db_session.add(stage)
        db_session.commit()
        db_session.refresh(stage)
        db_session.add(ReviewOpinionDetail(
            stage_id=stage.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=33,
            category="기타의견",
            severity="L0",
            content=f"{mgmt_no} 의견",
        ))
    db_session.commit()

    res = client.get(
        "/api/reviews/opinion-details",
        params={"batch": 1, "severity": "L0"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["mgmt_no"] == "2025-0100"

    res = client.get(
        "/api/reviews/opinion-details",
        params={"severity": "L0"},
        headers=headers,
    )
    assert res.json()["total"] == 2

    res = client.get(
        "/api/reviews/opinion-details",
        params={"batch": 9},
        headers=headers,
    )
    assert res.status_code == 400


def test_건물_상세에_배포차수_포함(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    building = Building(mgmt_no="2025-2669")
    db_session.add(building)
    db_session.commit()
    db_session.refresh(building)

    res = client.get(f"/api/buildings/{building.id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["deploy_batch"] == 4
