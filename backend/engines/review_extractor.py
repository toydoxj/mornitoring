"""검토서 내용 자동 추출 엔진

검토서 엑셀에서 판정 결과, 부적합 유형, 검토 의견 등을 추출하여
review_stages 테이블에 반영한다.
"""

from pathlib import Path

from openpyxl import load_workbook

from models.review_stage import ResultType


# 검토서 셀 위치 설정 (양식 변경 시 여기만 수정)
EXTRACT_CELL_CONFIG = {
    "result_cell": "B5",           # 판정 결과
    "defect_type_1_cell": "B6",    # 부적합유형-1
    "defect_type_2_cell": "B7",    # 부적합유형-2
    "defect_type_3_cell": "B8",    # 부적합유형-3
    "review_opinion_cell": "B9",   # 검토의견
}

RESULT_MAP = {
    "적합": ResultType.PASS,
    "보완": ResultType.SUPPLEMENT,
    "부적합": ResultType.FAIL,
    "경미": ResultType.MINOR,
}


def extract_review_data(file_path: str | Path) -> dict:
    """검토서 엑셀에서 주요 데이터를 추출

    Returns:
        {
            "result": ResultType | None,
            "defect_type_1": str | None,
            "defect_type_2": str | None,
            "defect_type_3": str | None,
            "review_opinion": str | None,
        }
    """
    data: dict = {
        "result": None,
        "defect_type_1": None,
        "defect_type_2": None,
        "defect_type_3": None,
        "review_opinion": None,
    }

    try:
        wb = load_workbook(str(file_path), data_only=True, read_only=True)
        ws = wb.active
        if ws is None:
            wb.close()
            return data

        # 판정 결과
        result_val = ws[EXTRACT_CELL_CONFIG["result_cell"]].value
        if result_val:
            result_str = str(result_val).strip()
            data["result"] = RESULT_MAP.get(result_str)

        # 부적합유형
        for i in range(1, 4):
            cell_key = f"defect_type_{i}_cell"
            cell_val = ws[EXTRACT_CELL_CONFIG[cell_key]].value
            if cell_val:
                data[f"defect_type_{i}"] = str(cell_val).strip()

        # 검토의견
        opinion_val = ws[EXTRACT_CELL_CONFIG["review_opinion_cell"]].value
        if opinion_val:
            data["review_opinion"] = str(opinion_val).strip()

        wb.close()

    except Exception:
        pass

    return data
