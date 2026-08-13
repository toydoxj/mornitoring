"""배포차수별 기준 단계 설정 + 접수 시 강제 보정 테스트.

규칙 — 기준 R, 자동 판별 C:
  C == R  정상 진행
  C <  R  기준보다 뒤처짐 → R의 접수 단계로 강제
  C >  R  기준보다 앞서감 → R의 제출 단계로 강제 (재접수로 알림 분리)
"""

from datetime import date

from models.building import Building
from models.deploy_batch_stage import DeployBatchStage
from models.review_stage import PhaseType, ReviewStage
from models.user import UserRole


def _set_batch_stage(db, batch_no: int, phase: str) -> None:
    db.add(DeployBatchStage(batch_no=batch_no, phase=phase))
    db.commit()


def _make_building(db, mgmt_no: str, phase: str | None, reviewer_name="검토위원A") -> Building:
    building = Building(
        mgmt_no=mgmt_no,
        current_phase=phase,
        assigned_reviewer_name=reviewer_name,
    )
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


# ===== 기준 단계 설정 API =====

def test_기준_단계_기본은_전체_미설정(client, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    res = client.get("/api/distribution/batch-stages", headers=headers)
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["batch_no"] for item in items] == [1, 2, 3, 4, 5]
    assert all(item["phase"] is None for item in items)


def test_총괄간사는_기준_단계를_수정한다(client, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    res = client.put(
        "/api/distribution/batch-stages",
        json={"items": [
            {"batch_no": 1, "phase": "supplement_3"},
            {"batch_no": 4, "phase": "preliminary"},
        ]},
        headers=headers,
    )
    assert res.status_code == 200
    stages = {item["batch_no"]: item["phase"] for item in res.json()["items"]}
    assert stages == {1: "supplement_3", 2: None, 3: None, 4: "preliminary", 5: None}


def test_기준_단계를_None으로_보내면_해제된다(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _set_batch_stage(db_session, 1, "supplement_1")

    res = client.put(
        "/api/distribution/batch-stages",
        json={"items": [{"batch_no": 1, "phase": None}]},
        headers=headers,
    )
    assert res.status_code == 200
    stages = {item["batch_no"]: item["phase"] for item in res.json()["items"]}
    assert stages[1] is None


def test_간사는_기준_단계를_수정할_수_없다(client, make_user):
    _, headers = make_user(UserRole.SECRETARY)
    res = client.put(
        "/api/distribution/batch-stages",
        json={"items": [{"batch_no": 1, "phase": "supplement_1"}]},
        headers=headers,
    )
    assert res.status_code == 403

    # 조회는 간사도 가능
    assert client.get("/api/distribution/batch-stages", headers=headers).status_code == 200


def test_알_수_없는_단계는_400(client, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    res = client.put(
        "/api/distribution/batch-stages",
        json={"items": [{"batch_no": 1, "phase": "supplement_9"}]},
        headers=headers,
    )
    assert res.status_code == 400


# ===== 접수 시 보정 =====

def test_기준보다_뒤처지면_기준_단계_접수로_강제(client, db_session, make_user):
    """3차수 기준 1차 보완인데 예비검토로 계산 → 1차 보완도서 접수."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _set_batch_stage(db_session, 3, "supplement_1")
    building = _make_building(db_session, "2025-1000", "assigned")   # C = preliminary

    res = client.post(
        "/api/distribution/receive",
        json={"mgmt_nos": ["2025-1000"], "received_date": "2026-08-12"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["updated"] == 1

    adjustment = body["adjustments"][0]
    assert adjustment["mgmt_no"] == "2025-1000"
    assert adjustment["deploy_batch"] == 3
    assert adjustment["expected_phase"] == "supplement_1"
    assert adjustment["calculated_phase"] == "preliminary"
    assert adjustment["corrected_phase"] == "supplement_1_received"
    assert adjustment["direction"] == "behind"

    db_session.refresh(building)
    assert building.current_phase == "supplement_1_received"
    stage = db_session.query(ReviewStage).filter_by(
        building_id=building.id, phase=PhaseType.SUPPLEMENT_1
    ).one()
    assert stage.doc_received_at.isoformat() == "2026-08-12"

    # 뒤처진 건은 일반 접수 알림
    assert body["notifications"][0]["re_receive"] is False
    assert "재접수" not in body["notifications"][0]["message"]


def test_기준보다_앞서가면_기준_단계_제출로_강제(client, db_session, make_user):
    """3차수 기준 1차 보완인데 2차 보완으로 계산 → 1차 보완검토서 제출."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _set_batch_stage(db_session, 3, "supplement_1")
    # C = supplement_2 (2차 보완으로 계산됨)
    building = _make_building(db_session, "2025-1000", "supplement_2_received")

    res = client.post(
        "/api/distribution/receive",
        json={"mgmt_nos": ["2025-1000"], "received_date": "2026-08-12"},
        headers=headers,
    )
    body = res.json()
    adjustment = body["adjustments"][0]
    assert adjustment["calculated_phase"] == "supplement_2"
    assert adjustment["corrected_phase"] == "supplement_1"
    assert adjustment["direction"] == "ahead"

    db_session.refresh(building)
    assert building.current_phase == "supplement_1"

    # 앞서간 건은 재접수로 알림이 분리된다
    notification = body["notifications"][0]
    assert notification["re_receive"] is True
    assert "재접수" in notification["message"]


def test_앞서간_건은_검토서_이력을_지우지_않는다(client, db_session, make_user):
    """제출 단계로 되돌리므로 이미 제출된 검토서 이력은 유지해야 한다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _set_batch_stage(db_session, 3, "supplement_1")
    building = _make_building(db_session, "2025-1000", "supplement_2_received")
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.SUPPLEMENT_1,
        phase_order=1,
        reviewer_name="검토위원A",
        report_submitted_at=date(2026, 7, 1),
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)

    client.post(
        "/api/distribution/receive",
        json={"mgmt_nos": ["2025-1000"], "received_date": "2026-08-12"},
        headers=headers,
    )

    db_session.refresh(stage)
    assert stage.report_submitted_at is not None       # 이력 유지
    assert stage.doc_received_at.isoformat() == "2026-08-12"   # 접수일은 갱신


def test_기준과_같으면_보정하지_않는다(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _set_batch_stage(db_session, 3, "supplement_1")
    building = _make_building(db_session, "2025-1000", "preliminary")   # C = supplement_1

    body = client.post(
        "/api/distribution/receive",
        json={"mgmt_nos": ["2025-1000"]},
        headers=headers,
    ).json()
    assert body["adjustments"] == []

    db_session.refresh(building)
    assert building.current_phase == "supplement_1_received"


def test_기준_미설정_차수는_기존_동작(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    # 3차수만 설정, 대상은 1차수 건물
    _set_batch_stage(db_session, 3, "supplement_1")
    building = _make_building(db_session, "2025-0100", "assigned")

    body = client.post(
        "/api/distribution/receive",
        json={"mgmt_nos": ["2025-0100"]},
        headers=headers,
    ).json()
    assert body["adjustments"] == []

    db_session.refresh(building)
    assert building.current_phase == "doc_received"


def test_최종완료_건은_보정_대상에서_제외(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _set_batch_stage(db_session, 3, "supplement_1")
    building = _make_building(db_session, "2025-1000", "completed")
    building.final_result = "pass"
    db_session.commit()

    body = client.post(
        "/api/distribution/receive",
        json={"mgmt_nos": ["2025-1000"]},
        headers=headers,
    ).json()
    assert body["adjustments"] == []

    db_session.refresh(building)
    assert building.current_phase == "completed"


def test_미리보기는_DB를_바꾸지_않는다(client, db_session, make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _set_batch_stage(db_session, 3, "supplement_1")
    building = _make_building(db_session, "2025-1000", "assigned")

    body = client.post(
        "/api/distribution/receive",
        json={"mgmt_nos": ["2025-1000", "없는번호"], "dry_run": True},
        headers=headers,
    ).json()
    assert body["dry_run"] is True
    assert body["updated"] == 1
    assert body["not_found"] == ["없는번호"]
    assert body["notifications"] == []
    assert body["adjustments"][0]["corrected_phase"] == "supplement_1_received"

    db_session.refresh(building)
    assert building.current_phase == "assigned"   # 그대로
    assert db_session.query(ReviewStage).count() == 0


def test_5차_보완_제출_상태도_기준이_낮으면_되돌린다(client, db_session, make_user):
    """자동 판별이 불가능한 상태(더 진행 불가)도 기준보다 앞선 것으로 본다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _set_batch_stage(db_session, 3, "supplement_2")
    building = _make_building(db_session, "2025-1000", "supplement_5")

    body = client.post(
        "/api/distribution/receive",
        json={"mgmt_nos": ["2025-1000"]},
        headers=headers,
    ).json()
    adjustment = body["adjustments"][0]
    assert adjustment["calculated_phase"] == "-"
    assert adjustment["direction"] == "ahead"
    assert adjustment["corrected_phase"] == "supplement_2"

    db_session.refresh(building)
    assert building.current_phase == "supplement_2"
