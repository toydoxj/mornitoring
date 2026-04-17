"""DB → 통합관리대장 엑셀 Export 엔진"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from sqlalchemy.orm import Session

from models.building import Building
from models.review_stage import ReviewStage, PhaseType
from engines.column_mapping import (
    BUILDING_COLUMN_MAP,
    PRELIMINARY_STAGE_MAP,
    SUPPLEMENT_SUBMIT_START_COLS,
    SUPPLEMENT_SUBMIT_OFFSETS,
    SUPPLEMENT_REVIEW_START_COLS,
    SUPPLEMENT_REVIEW_OFFSETS,
    FINAL_RESULT_COLUMN,
    col_letter_to_index,
    index_to_col_letter,
)

# 스타일 상수
HEADER_FONT = Font(bold=True, size=10)
HEADER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)


# Row 1 대분류 헤더 정의
ROW1_HEADERS = {
    "C": "대상 건축물 개요(허가대장 DB)",
    "AE": "예비도서 접수",
    "AF": "예비판정",
    "AN": "보완서류 제출(1차)",
    "AS": "보완자료 검토(1차)",
    "AZ": "보완서류 제출(2차)",
    "BE": "보완자료 검토(2차)",
    "BL": "보완서류 제출(3차)",
    "BQ": "보완자료 검토(3차)",
    "BX": "보완서류 제출(4차)",
    "CC": "보완자료 검토(4차)",
    "CJ": "결과보고",
}

# Row 2 상세 컬럼명 (역매핑)
FIELD_TO_LABEL = {
    "mgmt_no": "모니터링\n관리번호",
    "building_type": "건축구분",
    "sido": "시도명",
    "sigungu": "시군구명",
    "beopjeongdong": "법정동명",
    "land_type": "대지구분",
    "main_lot_no": "본번",
    "sub_lot_no": "부번",
    "special_lot_no": "특수지번",
    "building_name": "건물명",
    "main_structure": "주구조",
    "other_structure": "기타구조",
    "main_usage": "주용도",
    "other_usage": "기타용도",
    "gross_area": "연면적",
    "height": "높이",
    "floors_above": "지상층수",
    "floors_below": "지하층수",
    "is_special_structure": "특수구조물 여부",
    "is_high_rise": "고층 여부",
    "is_multi_use": "다중이용건축물 여부",
    "remarks": "비고",
    "architect_firm": "건축사(소속)",
    "architect_name": "건축사(성명)",
    "struct_eng_firm": "책임구조기술자(소속)",
    "struct_eng_name": "책임구조기술자(성명)",
    "high_risk_type": "고위험유형",
    "doc_received_at": "도서접수일",
    "report_submitted_at": "검토서 제출일",
    "reviewer_name": "검토자",
    "review_opinion": "검토의견",
    "defect_type_1": "부적합유형-1",
    "defect_type_2": "부적합유형-2",
    "defect_type_3": "부적합유형-3",
    "result": "판정 결과",
    "stage_remarks": "비고",
    "objection_filed": "이의신청 제출",
    "objection_content": "이의신청\n검토내용",
    "objection_reason": "이의신청 사유",
}

RESULT_LABELS = {
    "pass": "적합",
    "supplement": "보완",
    "fail": "부적합",
    "minor": "경미",
}


def _format_value(val, field_name: str):
    """DB 값을 엑셀 출력용으로 변환"""
    if val is None:
        return ""
    if field_name == "result" and hasattr(val, "value"):
        return RESULT_LABELS.get(val.value, str(val.value))
    if isinstance(val, bool):
        return "Y" if val else "N"
    return val


def export_ledger(db: Session) -> BytesIO:
    """DB 데이터를 통합관리대장 형식의 엑셀로 export

    Returns:
        BytesIO: 엑셀 파일 바이너리 스트림
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "통합 관리대장"

    # Row 1: 대분류 헤더
    for col_letter, label in ROW1_HEADERS.items():
        cell = ws.cell(row=1, column=col_letter_to_index(col_letter) + 1, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER_ALIGN
        cell.border = THIN_BORDER

    # Row 2: 상세 컬럼 헤더
    # 건축물 기본정보
    ws.cell(row=2, column=1, value="모니터링\n관리번호")
    ws.cell(row=2, column=2, value="검토\n위원")

    for col_letter, field_name in BUILDING_COLUMN_MAP.items():
        col_idx = col_letter_to_index(col_letter) + 1
        label = FIELD_TO_LABEL.get(field_name, field_name)
        cell = ws.cell(row=2, column=col_idx, value=label)
        cell.font = HEADER_FONT
        cell.alignment = CENTER_ALIGN
        cell.border = THIN_BORDER

    # 예비검토 헤더
    for col_letter, field_name in PRELIMINARY_STAGE_MAP.items():
        col_idx = col_letter_to_index(col_letter) + 1
        label = FIELD_TO_LABEL.get(field_name, field_name)
        cell = ws.cell(row=2, column=col_idx, value=label)
        cell.font = HEADER_FONT
        cell.alignment = CENTER_ALIGN
        cell.border = THIN_BORDER

    # 보완 단계 헤더 (1차~4차)
    for supp_no in range(1, 5):
        # 제출 헤더
        submit_start = SUPPLEMENT_SUBMIT_START_COLS[supp_no]
        for offset, field_name in SUPPLEMENT_SUBMIT_OFFSETS.items():
            col_idx = col_letter_to_index(submit_start) + offset + 1
            label = FIELD_TO_LABEL.get(field_name, field_name)
            cell = ws.cell(row=2, column=col_idx, value=label)
            cell.font = HEADER_FONT
            cell.alignment = CENTER_ALIGN
            cell.border = THIN_BORDER

        # 검토 헤더
        review_start = SUPPLEMENT_REVIEW_START_COLS[supp_no]
        for offset, field_name in SUPPLEMENT_REVIEW_OFFSETS.items():
            col_idx = col_letter_to_index(review_start) + offset + 1
            label = FIELD_TO_LABEL.get(field_name, field_name)
            cell = ws.cell(row=2, column=col_idx, value=label)
            cell.font = HEADER_FONT
            cell.alignment = CENTER_ALIGN
            cell.border = THIN_BORDER

    # 최종 판정 헤더
    final_col_idx = col_letter_to_index(FINAL_RESULT_COLUMN) + 1
    ws.cell(row=2, column=final_col_idx, value="최종\n판정결과").font = HEADER_FONT

    # 데이터 행 쓰기
    buildings = (
        db.query(Building)
        .order_by(Building.mgmt_no)
        .all()
    )

    # 전체 stages 일괄 조회
    all_stages = db.query(ReviewStage).order_by(ReviewStage.phase_order).all()
    stages_by_building: dict[int, list] = {}
    for stage in all_stages:
        if stage.building_id not in stages_by_building:
            stages_by_building[stage.building_id] = []
        stages_by_building[stage.building_id].append(stage)

    for row_offset, building in enumerate(buildings):
        row_num = 3 + row_offset

        # 기본정보 쓰기
        for col_letter, field_name in BUILDING_COLUMN_MAP.items():
            col_idx = col_letter_to_index(col_letter) + 1
            val = getattr(building, field_name, None)
            ws.cell(row=row_num, column=col_idx, value=_format_value(val, field_name))

        # 검토위원명 (B열)
        if building.assigned_reviewer_name:
            ws.cell(row=row_num, column=2, value=building.assigned_reviewer_name)
        elif building.reviewer and building.reviewer.user:
            ws.cell(row=row_num, column=2, value=building.reviewer.user.name)

        # 최종 판정
        if building.final_result:
            ws.cell(row=row_num, column=final_col_idx, value=building.final_result)

        # 검토 단계 데이터 (일괄 조회에서 가져오기)
        stages = stages_by_building.get(building.id, [])

        for stage in stages:
            if stage.phase == PhaseType.PRELIMINARY:
                # 예비검토
                for col_letter, field_name in PRELIMINARY_STAGE_MAP.items():
                    col_idx = col_letter_to_index(col_letter) + 1
                    val = getattr(stage, field_name, None)
                    ws.cell(row=row_num, column=col_idx, value=_format_value(val, field_name))
            else:
                # 보완 단계
                supp_no = stage.phase_order
                if supp_no < 1 or supp_no > 4:
                    continue

                # 제출 정보
                submit_start = SUPPLEMENT_SUBMIT_START_COLS[supp_no]
                for offset, field_name in SUPPLEMENT_SUBMIT_OFFSETS.items():
                    col_idx = col_letter_to_index(submit_start) + offset + 1
                    val = getattr(stage, field_name, None)
                    ws.cell(row=row_num, column=col_idx, value=_format_value(val, field_name))

                # 검토 정보
                review_start = SUPPLEMENT_REVIEW_START_COLS[supp_no]
                for offset, field_name in SUPPLEMENT_REVIEW_OFFSETS.items():
                    col_idx = col_letter_to_index(review_start) + offset + 1
                    val = getattr(stage, field_name, None)
                    ws.cell(row=row_num, column=col_idx, value=_format_value(val, field_name))

    # 열 너비 자동 조정 (주요 열)
    ws.column_dimensions["A"].width = 15
    ws.column_dimensions["B"].width = 10
    ws.column_dimensions["K"].width = 25

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    wb.close()
    return output
