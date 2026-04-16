"""단계 상태머신

예비검토 → 1차보완 → 2차보완 → ... → 완료
각 단계 전환 시 규칙을 정의한다.
"""

from models.review_stage import PhaseType, ResultType

# 단계 순서 정의
PHASE_SEQUENCE = [
    PhaseType.PRELIMINARY,
    PhaseType.SUPPLEMENT_1,
    PhaseType.SUPPLEMENT_2,
    PhaseType.SUPPLEMENT_3,
    PhaseType.SUPPLEMENT_4,
    PhaseType.SUPPLEMENT_5,
]

# 보완이 필요한 결과 (다음 단계로 진행해야 함)
REQUIRES_SUPPLEMENT = {ResultType.SUPPLEMENT, ResultType.FAIL}

# 완료 결과 (더 이상 보완 불필요)
COMPLETED_RESULTS = {ResultType.PASS, ResultType.MINOR}


def get_next_phase(current_phase: PhaseType) -> PhaseType | None:
    """현재 단계의 다음 단계를 반환. 마지막 단계면 None."""
    try:
        idx = PHASE_SEQUENCE.index(current_phase)
        if idx + 1 < len(PHASE_SEQUENCE):
            return PHASE_SEQUENCE[idx + 1]
    except ValueError:
        pass
    return None


def can_advance(current_result: ResultType | None) -> bool:
    """현재 결과로 다음 단계로 진행 가능한지 판단"""
    if current_result is None:
        return False
    return current_result in REQUIRES_SUPPLEMENT


def is_completed(current_result: ResultType | None) -> bool:
    """현재 결과가 완료 상태인지 판단"""
    if current_result is None:
        return False
    return current_result in COMPLETED_RESULTS


def get_phase_order(phase: PhaseType) -> int:
    """단계의 순서 번호를 반환"""
    try:
        return PHASE_SEQUENCE.index(phase)
    except ValueError:
        return 0
