"""재제출 요청 모델

검토위원이 배포받은 설계도서로 검토를 진행할 수 없을 때 재제출을 요청한다.
요청이 접수되면 건물의 current_phase 를 접수 직전 단계로 되돌리고 해당 단계의
검토서 요청 예정일(report_due_date)을 비운다. 재제출된 도서가 다시 접수될 때도
예정일은 비운 채로 두며(간사가 사유 확인 후 지정), 그 시점을 re_received_at 에
기록해 같은 요청으로 예정일이 반복해서 비워지지 않게 한다.

요청 사유는 총괄간사·조별간사·관리원(및 팀장)이 별도 메뉴에서 확인·처리한다.
building 이 사후 삭제되어도 이력이 남도록 mgmt_no 를 스냅샷으로 보관한다.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ResubmissionStatus(str, enum.Enum):
    PENDING = "pending"        # 대기
    COMPLETED = "completed"    # 처리완료


class ResubmissionRequest(Base):
    __tablename__ = "resubmission_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    building_id: Mapped[int | None] = mapped_column(
        ForeignKey("buildings.id", ondelete="SET NULL"), index=True
    )
    # 관리번호 스냅샷 — building 삭제 후에도 조회 가능
    mgmt_no: Mapped[str] = mapped_column(String(20), index=True)
    # 요청 대상 검토 단계 (review_stages.phase 값. 예: preliminary, supplement_1)
    phase: Mapped[str] = mapped_column(String(30))
    # 되돌리기 전/후 building.current_phase
    from_phase: Mapped[str | None] = mapped_column(String(30))
    to_phase: Mapped[str | None] = mapped_column(String(30))
    # 되돌리면서 비운 검토서 요청 예정일 (복원 판단용 기록)
    cleared_due_date: Mapped[str | None] = mapped_column(String(10))

    requester_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    requester_name: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(Text)

    # 이 요청 이후 도서가 다시 접수된 시각.
    # 재접수 때 검토서 요청 예정일을 비우는 대상을 "아직 재접수되지 않은 요청"으로
    # 한정하기 위한 표시이며, 상태 전환은 간사가 직접 한다.
    re_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[ResubmissionStatus] = mapped_column(
        Enum(ResubmissionStatus), default=ResubmissionStatus.PENDING
    )
    reply: Mapped[str | None] = mapped_column(Text)
    handled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
