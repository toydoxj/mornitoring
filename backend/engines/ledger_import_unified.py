"""통합 관리대장 시트 Import 엔진

'통합 관리대장' 시트 기준 (3차수 통합본).
Row 3: 대분류 헤더
Row 4: 상세 컬럼명
Row 5~: 데이터 (3400+ 행)
"""

from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from models.building import Building
from models.review_stage import ReviewStage, PhaseType, ResultType
from engines.column_mapping import col_letter_to_index

DATA_START_ROW = 5
SHEET_NAME = "통합 관리대장"

# 통합 관리대장 열 매핑 (Row 4 기준)
BUILDING_COLUMN_MAP = {
    "A": "mgmt_no",
    "C": "building_type",        # 건축구분
    "E": "sido",                 # 시도명
    "F": "sigungu",              # 시군구명
    "G": "beopjeongdong",        # 법정동명
    "H": "land_type",            # 대지구분
    "I": "main_lot_no",          # 본번
    "J": "sub_lot_no",           # 부번
    "K": "special_lot_no",       # 특수지번
    "L": "building_name",        # 건물명
    "M": "gross_area",           # 연면적
    "N": "main_structure",       # 주구조
    "O": "other_structure",      # 기타구조
    "P": "main_usage",           # 주용도
    "Q": "other_usage",          # 기타용도
    "T": "height",               # 높이
    "U": "floors_above",         # 지상층수
    "V": "floors_below",         # 지하층수
    "AL": "is_special_structure", # 특수구조물 여부
    "AM": "is_high_rise",        # 고층 여부
    "AN": "is_multi_use",        # 다중이용건축물 여부
    "AR": "architect_firm",      # 건축사(소속)
    "AS": "architect_name",      # 건축사(성명)
    "AT": "struct_eng_firm",     # 책임구조기술자(소속)
    "AU": "struct_eng_name",     # 책임구조기술자(성명)
    "AZ": "high_risk_type",      # 고위험유형
    "AP": "remarks",             # 비고
}

# 예비판정 매핑
PRELIMINARY_MAP = {
    "BQ": "reviewer_name",       # 검토자
    "BR": "review_opinion",      # 1차검토의견(기술사회)
    "BS": "defect_type_1",       # 부적합유형-1
    "BT": "defect_type_2",       # 부적합유형-2
    "BU": "defect_type_3",       # 부적합유형-3
    "BV": "result",              # 예비판정 결과
    "BW": "stage_remarks",       # 예비 검토의견
}

# 보완자료 검토(1차) 매핑
SUPPLEMENT_1_MAP = {
    "CI": "reviewer_name",       # 검토자
    "CJ": "result",              # 판정 결과
    "CK": "defect_type_1",       # 부적합유형-1
    "CL": "defect_type_2",       # 부적합유형-2
    "CM": "defect_type_3",       # 부적합유형-3
    "CN": "review_opinion",      # 검토의견
}

# 검토위원 열
REVIEWER_COLUMN = "DL"

# 최종 판정 열
FINAL_RESULT_COLUMN = "CW"


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
    if s in ("Y", "예", "○", "O", "1", "해당"):
        return True
    if s in ("N", "아니오", "×", "X", "0", "미해당"):
        return False
    return None


def _parse_result(val) -> ResultType | None:
    if val is None:
        return None
    s = str(val).strip()
    mapping = {
        "적합": ResultType.PASS,
        "보완": ResultType.SUPPLEMENT,
        "부적합": ResultType.FAIL,
        "경미": ResultType.MINOR,
    }
    return mapping.get(s)


def import_ledger_unified(file_path: str | Path, db: Session) -> dict:
    """통합 관리대장 시트를 DB에 import"""
    wb = load_workbook(str(file_path), data_only=True, read_only=True)

    if SHEET_NAME not in wb.sheetnames:
        wb.close()
        return {"imported": 0, "skipped": 0, "errors": [f"시트 '{SHEET_NAME}'을 찾을 수 없습니다"]}

    ws = wb[SHEET_NAME]
    result = {"imported": 0, "skipped": 0, "errors": []}

    for row in ws.iter_rows(min_row=DATA_START_ROW):
        mgmt_no = _cell_value(row, "A")
        if not mgmt_no:
            continue

        mgmt_no = str(mgmt_no).strip()
        if not (len(mgmt_no) >= 9 and "-" in mgmt_no):
            continue

        # 중복 체크
        existing = db.query(Building).filter(Building.mgmt_no == mgmt_no).first()
        if existing:
            result["skipped"] += 1
            continue

        # 건축물 기본정보
        building_data = {}
        for col_letter, field_name in BUILDING_COLUMN_MAP.items():
            val = _cell_value(row, col_letter)
            if field_name in ("gross_area", "height"):
                val = _to_float(val)
            elif field_name in ("floors_above", "floors_below"):
                val = _to_int(val)
            elif field_name in ("is_special_structure", "is_high_rise", "is_multi_use"):
                val = _to_bool(val)
            building_data[field_name] = val

        # 검토위원 이름 (DL열)
        reviewer_name = _cell_value(row, REVIEWER_COLUMN)
        if reviewer_name:
            building_data["assigned_reviewer_name"] = str(reviewer_name).strip()

        # 최종 판정
        final = _cell_value(row, FINAL_RESULT_COLUMN)
        if final:
            building_data["final_result"] = str(final)

        building = Building(**building_data)
        db.add(building)
        db.flush()

        # 예비검토 단계
        prelim_data = {}
        for col_letter, field_name in PRELIMINARY_MAP.items():
            val = _cell_value(row, col_letter)
            if field_name == "result":
                val = _parse_result(val)
            prelim_data[field_name] = val

        if any(v is not None for v in prelim_data.values()):
            stage = ReviewStage(
                building_id=building.id,
                phase=PhaseType.PRELIMINARY,
                phase_order=0,
                **prelim_data,
            )
            db.add(stage)
            building.current_phase = "preliminary"

        # 1차 보완 검토
        supp1_data = {}
        for col_letter, field_name in SUPPLEMENT_1_MAP.items():
            val = _cell_value(row, col_letter)
            if field_name == "result":
                val = _parse_result(val)
            supp1_data[field_name] = val

        if any(v is not None for v in supp1_data.values()):
            stage = ReviewStage(
                building_id=building.id,
                phase=PhaseType.SUPPLEMENT_1,
                phase_order=1,
                **supp1_data,
            )
            db.add(stage)
            building.current_phase = "supplement_1"

        result["imported"] += 1

    db.commit()
    wb.close()
    return result
