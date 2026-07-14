"""최종판정(final_result) 값 매핑 — import·비교검토 공용 상수.

통합 관리대장 CW열의 한글 표기(정규화 결과)를 DB 코드 값으로 변환한다.
`ledger_import_unified.py` 와 `ledger_phase_compare.py` 가 함께 사용하므로
두 곳의 매핑이 절대 어긋나지 않도록 반드시 이 파일에서만 수정한다.

6분류 체계 (+ 레거시):
    pass            적합(원적합)
    pass_supplement 보완적합
    fail_simple_error 부적합(단순오류)   ← 구분 없는 "부적합"도 여기로 (정책 결정 1)
    fail_recalculate  부적합(재계산)
    fail_no_response  부적합(미회신)
    excluded          대상제외
    fail            부적합(레거시) — 신규 기입 금지, 기존 데이터 표시용
"""

# 엑셀 최종판정 한글 표기(정규화 결과) → DB 코드 값.
# 셀 값은 조회 전에 괄호·공백·줄바꿈이 제거된 정규화 문자열로 변환되므로
# 괄호 없는 키가 실제 매칭에 쓰인다. 괄호 포함 키는 정규화 규칙이 바뀔 때를
# 대비한 안전용으로 함께 등록한다.
FINAL_RESULT_MAP = {
    "원적합": "pass",
    "적합": "pass",
    "보완적합": "pass_supplement",
    "부적합": "fail_simple_error",          # 구분 없으면 단순오류로 (정책 결정 1)
    "부적합단순오류": "fail_simple_error",
    "부적합(단순오류)": "fail_simple_error",
    "부적합재계산": "fail_recalculate",
    "부적합(재계산)": "fail_recalculate",
    "부적합미회신": "fail_no_response",
    "부적합(미회신)": "fail_no_response",
    "대상제외": "excluded",
}

# 정규화 결과가 이 집합에 있거나 아래 토큰을 포함하면 최종판정에서 제외한다.
# "이관"(차수 이관·재보완 N차수 이관)은 최종 완료가 아니라 다음 차수로 넘어간
# 상태이므로 final_result 를 설정하지 않고 완료 전환도 하지 않는다.
FINAL_RESULT_EXCLUDED_VALUES = {"차수이관"}
FINAL_RESULT_EXCLUDED_TOKENS = ("이관",)


def is_final_result_excluded(normalized: str) -> bool:
    """정규화된 최종판정 문자열이 제외 대상인지 판정한다."""
    if normalized in FINAL_RESULT_EXCLUDED_VALUES:
        return True
    return any(token in normalized for token in FINAL_RESULT_EXCLUDED_TOKENS)
