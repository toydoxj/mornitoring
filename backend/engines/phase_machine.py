"""단계 상태머신

흐름:
  예비도서 접수(doc_received)
  → 예비검토서 제출(preliminary)
  → 보완도서(1차) 접수(supplement_1_received)
  → 보완검토서(1차) 제출(supplement_1)
  → 보완도서(2차) 접수(supplement_2_received)
  → 보완검토서(2차) 제출(supplement_2)
  → ...
  → 완료(completed)
"""

from models.review_stage import ResultType

# 단계 순서 (문자열 기반)
PHASE_SEQUENCE = [
    "doc_received",
    "preliminary",
    "supplement_1_received",
    "supplement_1",
    "supplement_2_received",
    "supplement_2",
    "supplement_3_received",
    "supplement_3",
    "supplement_4_received",
    "supplement_4",
    "supplement_5_received",
    "supplement_5",
    "completed",
]

# 다음 단계로 진행되는 결과 — 현재 모든 판정 결과가 다음 단계로 진행됨
# 최종 완료는 별도 엑셀 업로드로 지정할 예정이므로 여기서는 완료 처리하지 않음
REQUIRES_SUPPLEMENT = {
    ResultType.PASS,
    ResultType.SIMPLE_ERROR,
    ResultType.RECALCULATE,
    ResultType.SUPPLEMENT,
    ResultType.FAIL,
    ResultType.MINOR,
}

# 검토서 업로드 흐름에서 자동 완료 처리 비활성화
COMPLETED_RESULTS: set[ResultType] = set()


def get_next_phase(current_phase: str) -> str | None:
    """현재 단계의 다음 단계를 반환"""
    try:
        idx = PHASE_SEQUENCE.index(current_phase)
        if idx + 1 < len(PHASE_SEQUENCE):
            return PHASE_SEQUENCE[idx + 1]
    except ValueError:
        pass
    return None


def can_advance(current_result: ResultType | None) -> bool:
    """보완 필요 여부"""
    if current_result is None:
        return False
    return current_result in REQUIRES_SUPPLEMENT


def is_completed(current_result: ResultType | None) -> bool:
    """완료 상태 여부"""
    if current_result is None:
        return False
    return current_result in COMPLETED_RESULTS


def get_phase_order(phase: str) -> int:
    """단계 순서 번호"""
    try:
        return PHASE_SEQUENCE.index(phase)
    except ValueError:
        return 0
