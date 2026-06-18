"""2026년 기술사회 배포용 관리대장 엑셀 → DB Import 엔진

시트명: 관리대장
Row 3: 대분류 헤더
Row 4: 상세 컬럼명
Row 5~: 데이터
"""

from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from models.building import Building
from models.review_stage import ReviewStage, PhaseType, ResultType
from services.phase_transition import transition_phase
from engines.column_mapping import col_letter_to_index

DATA_START_ROW = 5
SHEET_NAME = "관리대장"

# 2026년 기술사회 배포용 관리대장 열 매핑 (Row 4 기준)
BUILDING_COLUMN_MAP_TECHNICAL = {
    "A": "mgmt_no",              # 모니터링 관리번호
    "F": "building_type",        # 건축구분
    "H": "sido",                 # 시도명
    "I": "sigungu",              # 시군구명
    "J": "beopjeongdong",        # 법정동명
    "K": "land_type",            # 대지구분
    "L": "main_lot_no",          # 본번
    "M": "sub_lot_no",           # 부번
    "N": "special_lot_no",       # 특수지번
    "O": "building_name",        # 건물명
    "P": "gross_area",           # 연면적
    "Q": "main_structure",       # 주구조
    "R": "other_structure",      # 기타구조
    "S": "main_usage",           # 주용도
    "T": "other_usage",          # 기타용도
    "W": "height",               # 높이
    "X": "floors_above",         # 지상층수
    "Y": "floors_below",         # 지하층수
    "AD": "architect_name",      # 설계자
    "AE": "architect_firm",      # 설계사무소
    "AO": "is_special_structure", # 특수구조물 여부
    "AP": "is_high_rise",        # 고층 여부
    "AQ": "is_multi_use",        # 다중이용건축물 여부
    "AS": "remarks",             # 비고
}

PRELIMINARY_MAP_TECHNICAL = {
    "AT": "reviewer_name",       # 검토자
    "AU": "review_opinion",      # 1차검토의견(기술사회)
    "AV": "defect_type_1",       # 부적합유형-1
    "AW": "defect_type_2",       # 부적합유형-2
    "AX": "defect_type_3",       # 부적합유형-3
    "AY": "result",              # 예비판정 결과
    "AZ": "stage_remarks",       # 예비 검토의견
}

SUPPLEMENT_1_MAP_TECHNICAL = {
    "BG": "reviewer_name",       # 검토자
    "BH": "result",              # 판정 결과
    "BI": "defect_type_1",       # 부적합유형-1
    "BJ": "defect_type_2",       # 부적합유형-2
    "BK": "defect_type_3",       # 부적합유형-3
    "BL": "review_opinion",      # 보완자료 판정결과 검토의견
    "BM": "stage_remarks",       # 비고
}

ASSIGNED_REVIEWER_COLUMNS = ("AT", "BG", "B")
HIGH_RISK_COLUMN = "AR"


def _cell_value(row: tuple, col_letter: str):
    idx = col_letter_to_index(col_letter)
    if idx >= len(row):
        return None
    val = row[idx].value
    if isinstance(val, str):
        val = val.strip()
        if val == "":
            return None
    return val


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _to_bool(val) -> bool | None:
    if val is None:
        return None
    s = str(val).strip()
    if s in ("Y", "예", "○", "O", "o", "1", "True", "true", "해당"):
        return True
    if s in ("N", "아니오", "×", "X", "x", "0", "False", "false", "미해당", "-"):
        return False
    return None


def _to_high_risk_type(val) -> str | None:
    is_high_risk = _to_bool(val)
    if is_high_risk is True:
        return "고위험"
    if is_high_risk is False or val is None:
        return None
    return str(val).strip()


def _parse_result(val) -> ResultType | None:
    if val is None:
        return None
    s = str(val).strip()
    mapping = {
        "적합": ResultType.PASS,
        "단순오류": ResultType.SIMPLE_ERROR,
        "경미": ResultType.SIMPLE_ERROR,
        "재계산": ResultType.RECALCULATE,
        "보완": ResultType.RECALCULATE,
        "부적합": ResultType.RECALCULATE,
    }
    return mapping.get(s)


def _is_mgmt_no(value) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return len(text) >= 9 and "-" in text


def _first_present(row: tuple, col_letters: tuple[str, ...]) -> str | None:
    for col_letter in col_letters:
        value = _cell_value(row, col_letter)
        if value:
            return str(value).strip()
    return None


def _find_sheet(wb) -> str | None:
    if SHEET_NAME in wb.sheetnames:
        return SHEET_NAME
    for sheet_name in wb.sheetnames:
        if "관리대장" in sheet_name:
            return sheet_name
    return None


def import_ledger_technical(
    file_path: str | Path,
    db: Session,
    actor_user_id: int | None = None,
) -> dict:
    """2026년 기술사회 배포용 관리대장 파일을 DB에 import한다."""
    wb = load_workbook(str(file_path), data_only=True, read_only=True)
    matched_sheet = _find_sheet(wb)

    if matched_sheet is None:
        wb.close()
        return {"imported": 0, "skipped": 0, "errors": ["관리대장 시트를 찾을 수 없습니다"]}

    ws = wb[matched_sheet]
    rows_parsed = []
    for row in ws.iter_rows(min_row=DATA_START_ROW):
        mgmt_no = _cell_value(row, "A")
        if not _is_mgmt_no(mgmt_no):
            continue
        rows_parsed.append((str(mgmt_no).strip(), row))
    wb.close()

    if not rows_parsed:
        return {"imported": 0, "skipped": 0, "errors": [], "sheet": matched_sheet}

    all_mgmt_nos = [mgmt_no for mgmt_no, _ in rows_parsed]
    existing_set: set[str] = set()
    for i in range(0, len(all_mgmt_nos), 1000):
        chunk = all_mgmt_nos[i:i + 1000]
        existing = db.query(Building.mgmt_no).filter(Building.mgmt_no.in_(chunk)).all()
        existing_set.update(r[0] for r in existing)

    result = {"imported": 0, "skipped": 0, "errors": [], "sheet": matched_sheet}
    batch_count = 0

    for mgmt_no, row in rows_parsed:
        if mgmt_no in existing_set:
            result["skipped"] += 1
            continue

        building_data = {}
        for col_letter, field_name in BUILDING_COLUMN_MAP_TECHNICAL.items():
            val = _cell_value(row, col_letter)
            if field_name in ("gross_area", "height"):
                val = _to_float(val)
            elif field_name in ("floors_above", "floors_below"):
                val = _to_int(val)
            elif field_name in ("is_special_structure", "is_high_rise", "is_multi_use"):
                val = _to_bool(val)
            building_data[field_name] = val

        assigned_reviewer_name = _first_present(row, ASSIGNED_REVIEWER_COLUMNS)
        if assigned_reviewer_name:
            building_data["assigned_reviewer_name"] = assigned_reviewer_name

        high_risk_type = _to_high_risk_type(_cell_value(row, HIGH_RISK_COLUMN))
        if high_risk_type:
            building_data["high_risk_type"] = high_risk_type

        building = Building(**building_data)
        db.add(building)
        db.flush()
        existing_set.add(mgmt_no)

        prelim_data = {}
        for col_letter, field_name in PRELIMINARY_MAP_TECHNICAL.items():
            val = _cell_value(row, col_letter)
            if field_name == "result":
                val = _parse_result(val)
            prelim_data[field_name] = val

        if any(v is not None for v in prelim_data.values()):
            db.add(
                ReviewStage(
                    building_id=building.id,
                    phase=PhaseType.PRELIMINARY,
                    phase_order=0,
                    **prelim_data,
                )
            )
            transition_phase(
                db,
                building,
                to_phase="preliminary",
                trigger="import",
                actor_user_id=actor_user_id,
                reason="ledger_import_technical",
            )

        supp1_data = {}
        for col_letter, field_name in SUPPLEMENT_1_MAP_TECHNICAL.items():
            val = _cell_value(row, col_letter)
            if field_name == "result":
                val = _parse_result(val)
            supp1_data[field_name] = val

        if any(v is not None for v in supp1_data.values()):
            db.add(
                ReviewStage(
                    building_id=building.id,
                    phase=PhaseType.SUPPLEMENT_1,
                    phase_order=1,
                    **supp1_data,
                )
            )
            transition_phase(
                db,
                building,
                to_phase="supplement_1",
                trigger="import",
                actor_user_id=actor_user_id,
                reason="ledger_import_technical",
            )

        result["imported"] += 1
        batch_count += 1

        if batch_count % 500 == 0:
            db.commit()

    db.commit()
    return result
