"""통합관리대장 엑셀 ↔ DB 열 매핑 설정

관리대장 샘플.xlsx의 '통합 관리대장' 시트 기준.
Row 1: 대분류 헤더 (병합 셀)
Row 2: 상세 컬럼명
Row 3~: 데이터
"""

# 엑셀 열(Column letter) → DB 필드명 매핑
# 통합 관리대장 시트의 Row 2 기준
BUILDING_COLUMN_MAP: dict[str, str] = {
    "A": "mgmt_no",              # 모니터링 관리번호
    "C": "building_type",        # 건축구분
    "D": "sido",                 # 시도명
    "E": "sigungu",              # 시군구명
    "F": "beopjeongdong",        # 법정동명
    "G": "land_type",            # 대지구분
    "H": "main_lot_no",          # 본번
    "I": "sub_lot_no",           # 부번
    "J": "special_lot_no",       # 특수지번
    "K": "building_name",        # 건물명
    "L": "main_structure",       # 주구조
    "M": "other_structure",      # 기타구조
    "N": "main_usage",           # 주용도
    "O": "other_usage",          # 기타용도
    "P": "gross_area",           # 연면적
    "Q": "height",               # 높이
    "R": "floors_above",         # 지상층수
    "S": "floors_below",         # 지하층수
    "T": "is_special_structure", # 특수구조물 여부
    "U": "is_high_rise",         # 고층 여부
    "V": "is_multi_use",         # 다중이용건축물 여부
    "W": "remarks",              # 비고
    "X": "architect_firm",       # 건축사(소속)
    "Y": "architect_name",       # 건축사(성명)
    "Z": "struct_eng_firm",      # 책임구조기술자(소속)
    "AA": "struct_eng_name",     # 책임구조기술자(성명)
    "AB": "high_risk_type",      # 고위험유형
}

# 검토위원 열 (B열)
REVIEWER_COLUMN = "B"

# 예비검토 관련 열 매핑
PRELIMINARY_STAGE_MAP: dict[str, str] = {
    "AE": "doc_received_at",     # 도서접수일
    "AF": "report_submitted_at", # 검토서 제출일
    "AG": "reviewer_name",       # 검토자
    "AH": "review_opinion",      # 1차검토의견(기술사회)
    "AI": "defect_type_1",       # 부적합유형-1
    "AJ": "defect_type_2",       # 부적합유형-2
    "AK": "defect_type_3",       # 부적합유형-3
    "AL": "result",              # 예비판정 결과
    "AM": "stage_remarks",       # 예비 검토의견
}

# 보완 제출 열 매핑 (1차~4차 동일 패턴, 시작 열만 다름)
# 각 보완 차수의 시작 열
SUPPLEMENT_SUBMIT_START_COLS = {
    1: "AN",   # 보완서류 제출(1차)
    2: "AZ",   # 보완서류 제출(2차)
    3: "BL",   # 보완서류 제출(3차)
    4: "BX",   # 보완서류 제출(4차)
}

# 보완 제출 상대 오프셋 (시작 열로부터의 오프셋)
SUPPLEMENT_SUBMIT_OFFSETS: dict[int, str] = {
    0: "doc_received_at",       # 보완서류 접수일
    1: "objection_filed",       # 이의신청 제출
    2: "objection_content",     # 이의신청 검토내용
    3: "objection_reason",      # 이의신청 사유
    4: "stage_remarks",         # 비고
}

# 보완 검토 열 매핑
SUPPLEMENT_REVIEW_START_COLS = {
    1: "AS",   # 보완자료 검토(1차)
    2: "BE",   # 보완자료 검토(2차)
    3: "BQ",   # 보완자료 검토(3차)
    4: "CC",   # 보완자료 검토(4차)
}

# 보완 검토 상대 오프셋
SUPPLEMENT_REVIEW_OFFSETS: dict[int, str] = {
    0: "report_submitted_at",   # 검토서 제출일
    1: "result",                # 판정 결과
    2: "defect_type_1",         # 부적합유형-1
    3: "defect_type_2",         # 부적합유형-2
    4: "defect_type_3",         # 부적합유형-3
    5: "review_opinion",        # 검토의견
    6: "stage_remarks",         # 비고
}

# 최종 판정 열
FINAL_RESULT_COLUMN = "CJ"  # 최종 판정결과


def col_letter_to_index(col: str) -> int:
    """엑셀 열 문자를 0-based 인덱스로 변환 (A=0, B=1, ..., Z=25, AA=26)"""
    result = 0
    for char in col.upper():
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result - 1


def index_to_col_letter(index: int) -> str:
    """0-based 인덱스를 엑셀 열 문자로 변환"""
    result = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result
