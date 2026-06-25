from datetime import date

from openpyxl import Workbook

from engines.ledger_phase_compare import compare_supplement_phase_with_db
from models.user import UserRole


def _make_supplement_workbook(path, rows: list[dict[str, object]]) -> None:
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

    mismatched = make_building(mgmt_no="2026-0002")
    mismatched.current_phase = "supplement_1_received"

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
    )

    result = compare_supplement_phase_with_db(path, db_session, current_user=user)

    assert result["total_rows"] == 4
    assert result["matched"] == 1
    assert result["mismatched"] == 1
    assert result["missing_db"] == 2

    items = {item["mgmt_no"]: item for item in result["items"]}
    assert items["2026-0001"]["status"] == "matched"
    assert items["2026-0001"]["excel_phase"] == "supplement_2_received"
    assert items["2026-0001"]["evidence_column"] == "U"
    assert items["2026-0001"]["reviewer_name"] == "검토자1"

    assert items["2026-0002"]["status"] == "mismatch"
    assert items["2026-0002"]["excel_phase"] == "supplement_1"
    assert items["2026-0002"]["db_phase"] == "supplement_1_received"
    assert items["2026-0002"]["phase_direction"] == "excel_ahead"

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
