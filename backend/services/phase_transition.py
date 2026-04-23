"""Building.current_phase 전환 가드 + 영구 로그.

도메인 정책상 phase 전환은 8개 매트릭스 외에 발생해선 안 된다.
모든 변경(자동 트리거 + 간사 수동)은 phase_transition_logs 테이블에
관리번호별 영구 기록한다.

매트릭스:
    INITIAL: (none/"") -> "assigned"
    RECEIVE: "assigned"            -> "doc_received"
             "preliminary"         -> "supplement_1_received"
             "supplement_N"        -> "supplement_(N+1)_received"  (N=1~4)
    UPLOAD:  "doc_received"        -> "preliminary"
             "supplement_N_received" -> "supplement_N"             (N=1~5)
    MANUAL:  RECEIVE/UPLOAD 매트릭스 합집합 (임의 점프/역행 금지)

사용 패턴:
    log = transition_phase(db, building, to_phase=..., trigger="receive",
                           actor_user_id=user.id, ip_address=ip)
    # 호출자가 db.commit() 책임. log == None 이면 no-op (로그 미생성).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from models.building import Building
from models.phase_transition_log import PhaseTransitionLog


TriggerType = Literal["initial", "receive", "upload", "manual"]


# RECEIVE: (출발 phase) -> (도착 phase)
_RECEIVE_MATRIX: dict[str, str] = {
    "assigned": "doc_received",
    "preliminary": "supplement_1_received",
    "supplement_1": "supplement_2_received",
    "supplement_2": "supplement_3_received",
    "supplement_3": "supplement_4_received",
    "supplement_4": "supplement_5_received",
}

# UPLOAD: (출발 phase) -> (도착 phase). 출발은 반드시 _received로 끝나는 단계.
_UPLOAD_MATRIX: dict[str, str] = {
    "doc_received": "preliminary",
    "supplement_1_received": "supplement_1",
    "supplement_2_received": "supplement_2",
    "supplement_3_received": "supplement_3",
    "supplement_4_received": "supplement_4",
    "supplement_5_received": "supplement_5",
}

# INITIAL: 신규 건물 등록 직후. 출발은 None 또는 빈 문자열.
_INITIAL_TARGET = "assigned"

# MANUAL이 허용하는 (from, to) 쌍 — RECEIVE/UPLOAD 매트릭스의 합집합.
_MANUAL_ALLOWED_PAIRS: set[tuple[str, str]] = (
    {(f, t) for f, t in _RECEIVE_MATRIX.items()}
    | {(f, t) for f, t in _UPLOAD_MATRIX.items()}
)


class InvalidPhaseTransition(ValueError):
    """매트릭스에 없는 (trigger, from, to) 전환 시도."""


def next_phase_for(trigger: TriggerType, from_phase: str | None) -> str | None:
    """주어진 trigger + 출발 phase에 대한 도착 phase. 매트릭스에 없으면 None.

    호출처에서 'no-op'을 자연스럽게 판별하기 위한 헬퍼.
    """
    if trigger == "initial":
        return _INITIAL_TARGET if not from_phase else None
    if trigger == "receive":
        return _RECEIVE_MATRIX.get(from_phase or "")
    if trigger == "upload":
        return _UPLOAD_MATRIX.get(from_phase or "")
    return None


def _validate_transition(trigger: TriggerType, from_phase: str | None, to_phase: str) -> None:
    """매트릭스 검증. 위반 시 InvalidPhaseTransition raise."""
    if trigger == "initial":
        if from_phase:
            raise InvalidPhaseTransition(
                f"INITIAL 전환은 신규 건물(phase 없음)에서만 가능. 현재 from='{from_phase}'"
            )
        if to_phase != _INITIAL_TARGET:
            raise InvalidPhaseTransition(
                f"INITIAL 전환은 'assigned'만 허용. to='{to_phase}'"
            )
        return

    if trigger == "receive":
        expected = _RECEIVE_MATRIX.get(from_phase or "")
        if expected is None:
            raise InvalidPhaseTransition(
                f"RECEIVE 전환 불허: from='{from_phase}' 는 매트릭스에 없음"
            )
        if to_phase != expected:
            raise InvalidPhaseTransition(
                f"RECEIVE 전환 불허: from='{from_phase}' → '{to_phase}' (예상 '{expected}')"
            )
        return

    if trigger == "upload":
        expected = _UPLOAD_MATRIX.get(from_phase or "")
        if expected is None:
            raise InvalidPhaseTransition(
                f"UPLOAD 전환 불허: from='{from_phase}' 는 _received 단계가 아님 "
                "(검토서 데이터 갱신은 허용되나 phase 전환은 금지)"
            )
        if to_phase != expected:
            raise InvalidPhaseTransition(
                f"UPLOAD 전환 불허: from='{from_phase}' → '{to_phase}' (예상 '{expected}')"
            )
        return

    if trigger == "manual":
        if not from_phase:
            raise InvalidPhaseTransition(
                "MANUAL 전환은 from_phase가 비어 있을 수 없음 (INITIAL을 사용)"
            )
        if (from_phase, to_phase) not in _MANUAL_ALLOWED_PAIRS:
            raise InvalidPhaseTransition(
                f"MANUAL 전환 불허: ({from_phase} → {to_phase}) 는 매트릭스에 없음. "
                "임의 점프/역행은 금지. 데이터 복구는 운영 절차로 처리하세요."
            )
        return

    raise InvalidPhaseTransition(f"알 수 없는 트리거: {trigger}")


def transition_phase(
    db: Session,
    building: Building,
    *,
    to_phase: str | None,
    trigger: TriggerType,
    actor_user_id: int | None = None,
    ip_address: str | None = None,
    reason: str | None = None,
) -> PhaseTransitionLog | None:
    """`building.current_phase` 를 `to_phase` 로 전환하고 로그를 add 한다.

    - to_phase 가 None 이거나 building.current_phase 와 같으면 no-op (로그 미생성).
    - 매트릭스 위반 시 InvalidPhaseTransition raise (호출자가 400/500 매핑).
    - commit 은 호출자 책임 (배치 호출에서 트랜잭션을 묶기 위함).
    """
    if to_phase is None:
        return None
    from_phase = building.current_phase
    if from_phase == to_phase:
        return None

    _validate_transition(trigger, from_phase, to_phase)

    building.current_phase = to_phase
    log = PhaseTransitionLog(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        from_phase=from_phase,
        to_phase=to_phase,
        trigger=trigger,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        reason=reason,
    )
    db.add(log)
    return log
