from datetime import date

from openpyxl import Workbook

from engines.ledger_phase_compare import (
    apply_final_results_from_ledger,
    compare_supplement_phase_with_db,
)
from models.phase_transition_log import PhaseTransitionLog
from models.user import UserRole


def _make_supplement_workbook(
    path,
    rows: list[dict[str, object]],
    management_rows: list[dict[str, object]] | None = None,
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "통합 보완대장"
    ws["A4"] = "모니터링\n관리번호"
    for col in ("S", "U", "W", "Y", "AA"):
        ws[f"{col}4"] = "접수일자"
    for col in ("AV", "BD", "BL", "BT", "CB"):
        ws[f"{col}4"] = "보완자료검토서\n제출일"

    for row_no, row in enumerate(rows, start=5):
        for col, value in row.items():
            ws[f"{col}{row_no}"] = value

    if management_rows is not None:
        management_ws = wb.create_sheet("통합 관리대장")
        management_ws["A4"] = "모니터링\n관리번호"
        management_ws["CW4"] = "최종\n판정결과"
        for row_no, row in enumerate(management_rows, start=5):
            for col, value in row.items():
                management_ws[f"{col}{row_no}"] = value

    wb.save(path)


def test_compare_supplement_phase_with_db_detects_match_and_mismatch(
    db_session,
    make_user,
    make_building,
    tmp_path,
):
    user, _ = make_user(UserRole.CHIEF_SECRETARY)
    matched = make_building(mgmt_no="2026-0001")
    matched.current_phase = "supplement_2_received"
    matched.assigned_reviewer_name = "검토자1"
    matched.final_result = "pass"

    mismatched = make_building(mgmt_no="2026-0002")
    mismatched.current_phase = "supplement_1_received"
    mismatched.final_result = None

    db_session.commit()

    path = tmp_path / "phase_compare.xlsx"
    _make_supplement_workbook(
        path,
        [
            {"A": "2026-0001", "S": date(2026, 4, 1), "AV": date(2026, 4, 5), "U": date(2026, 4, 10)},
            {"A": "2026-0002", "S": date(2026, 4, 1), "AV": date(2026, 4, 5)},
            {"A": "2026-9999", "S": date(2026, 4, 1)},
            {"A": "2026-0003"},
        ],
        management_rows=[
            {"A": "2026-0001", "CW": "적합"},
            {"A": "2026-0002", "CW": "부적합"},
        ],
    )

    result = compare_supplement_phase_with_db(path, db_session, current_user=user)

    assert result["total_rows"] == 4
    assert result["matched"] == 1
    assert result["mismatched"] == 1
    assert result["missing_db"] == 2
    assert result["final_result_matched"] == 1
    assert result["final_result_mismatched"] == 1

    items = {item["mgmt_no"]: item for item in result["items"]}
    assert items["2026-0001"]["status"] == "matched"
    assert items["2026-0001"]["excel_phase"] == "supplement_2_received"
    assert items["2026-0001"]["evidence_column"] == "U"
    assert items["2026-0001"]["reviewer_name"] == "검토자1"

    assert items["2026-0002"]["status"] == "mismatch"
    assert items["2026-0002"]["excel_phase"] == "supplement_1"
    assert items["2026-0002"]["db_phase"] == "supplement_1_received"
    assert items["2026-0002"]["phase_direction"] == "excel_ahead"
    assert items["2026-0002"]["final_result_status"] == "mismatch"
    assert items["2026-0002"]["excel_final_result"] == "fail"
    assert items["2026-0002"]["final_result_column"] == "CW"

    assert items["2026-9999"]["status"] == "missing_db"


def test_phase_compare_endpoint_returns_summary(
    client,
    db_session,
    make_user,
    make_building,
    tmp_path,
):
    _, headers = make_user(UserRole.MANAGER)
    building = make_building(mgmt_no="2026-0101")
    building.current_phase = "supplement_1"
    db_session.commit()

    path = tmp_path / "phase_compare.xlsx"
    _make_supplement_workbook(
        path,
        [{"A": "2026-0101", "S": date(2026, 5, 1), "AV": date(2026, 5, 7)}],
    )

    with path.open("rb") as file:
        response = client.post(
            "/api/ledger/phase-compare",
            files={
                "file": (
                    "phase_compare.xlsx",
                    file,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["matched"] == 1
    assert data["items"][0]["mgmt_no"] == "2026-0101"
    assert data["items"][0]["status"] == "matched"
    assert data["items"][0]["final_result_status"] == "not_checked"


def test_apply_final_results_from_ledger_updates_only_mismatched_final_result(
    db_session,
    make_user,
    make_building,
    tmp_path,
):
    user, _ = make_user(UserRole.CHIEF_SECRETARY)
    building = make_building(mgmt_no="2026-0201")
    building.current_phase = "supplement_2"
    building.final_result = "pass"
    matched = make_building(mgmt_no="2026-0202")
    matched.current_phase = "supplement_1"
    matched.final_result = "fail"
    transfer = make_building(mgmt_no="2026-0203")
    transfer.current_phase = "preliminary"
    transfer.final_result = None
    db_session.commit()

    path = tmp_path / "final_result_apply.xlsx"
    _make_supplement_workbook(
        path,
        [],
        management_rows=[
            {"A": "2026-0201", "CW": "부적합"},
            {"A": "2026-0202", "CW": "부적합"},
            {"A": "2026-0203", "CW": "차수이관"},
            {"A": "2026-9999", "CW": "적합"},
        ],
    )

    result = apply_final_results_from_ledger(
        path,
        db_session,
        actor_user_id=user.id,
    )
    db_session.commit()

    assert result["updated"] == 1
    assert result["matched"] == 1
    assert result["missing_db"] == 1
    assert result["excel_final_result_missing"] == 1

    db_session.refresh(building)
    db_session.refresh(matched)
    db_session.refresh(transfer)
    assert building.final_result == "fail"
    assert building.current_phase == "completed"
    assert matched.final_result == "fail"
    assert matched.current_phase == "supplement_1"
    assert transfer.final_result is None
    assert transfer.current_phase == "preliminary"

    phase_log = db_session.query(PhaseTransitionLog).filter_by(mgmt_no="2026-0201").one()
    assert phase_log.from_phase == "supplement_2"
    assert phase_log.to_phase == "completed"


def test_final_results_apply_endpoint_returns_summary(
    client,
    db_session,
    make_user,
    make_building,
    tmp_path,
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    building = make_building(mgmt_no="2026-0301")
    building.current_phase = "preliminary"
    building.final_result = None
    db_session.commit()

    path = tmp_path / "final_result_endpoint.xlsx"
    _make_supplement_workbook(
        path,
        [],
        management_rows=[{"A": "2026-0301", "CW": "보완적합"}],
    )

    with path.open("rb") as file:
        response = client.post(
            "/api/ledger/final-results/apply",
            files={
                "file": (
                    "final_result_endpoint.xlsx",
                    file,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["updated"] == 1
    db_session.refresh(building)
    assert building.final_result == "pass_supplement"
    assert building.current_phase == "completed"
