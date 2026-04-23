"""건축물 단계(current_phase) 전환 영구 로그.

도메인 정책상 phase 전환은 8개 매트릭스 외에 발생해선 안 되며, 발생한 경우
시스템 트리거(도서접수/검토서업로드)와 간사 수동 변경 모두 영구 기록한다.
관리번호별 빠른 조회를 위해 mgmt_no는 building_id와 별개로 스냅샷 저장.
building이 사후 삭제되어도 이력 추적이 가능해야 하므로 FK는 SET NULL.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PhaseTransitionLog(Base):
    __tablename__ = "phase_transition_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # building 삭제 시 로그는 살린다 (이력 추적 우선).
    building_id: Mapped[int | None] = mapped_column(
        ForeignKey("buildings.id", ondelete="SET NULL"), index=True
    )
    # 관리번호 스냅샷 — building 삭제 후에도 조회 가능 + 인덱스로 관리번호별 타임라인 빠르게.
    mgmt_no: Mapped[str] = mapped_column(String(50), index=True)
    from_phase: Mapped[str | None] = mapped_column(String(50))
    to_phase: Mapped[str] = mapped_column(String(50))
    # 트리거: initial / receive / upload / manual
    trigger: Mapped[str] = mapped_column(String(20))
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    # 수동 변경 시 사유, 자동 트리거에서는 부가 메타(예: receive 호출 ID)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
