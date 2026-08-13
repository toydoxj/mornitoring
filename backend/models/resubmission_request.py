"""재제출 요청 모델

검토위원이 배포받은 설계도서로 검토를 진행할 수 없을 때 재제출을 요청한다.
등록은 사유 접수까지만이고 건물 상태는 그대로 둔다. 사유를 확인한 간사가 요청
화면에서 단계 되돌리기(결과는 to_phase)와 검토서 요청 예정일 삭제(삭제한 값은
cleared_due_date)를 실행한다. 재제출된 도서가 다시 접수되면 예정일은 일반 접수와
똑같이 새로 부여되고, 그 시점이 re_received_at 에 남아 간사가 요청을 닫을 시점을
판단할 수 있게 한다.

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
    # 요청 시점의 building.current_phase
    from_phase: Mapped[str | None] = mapped_column(String(30))
    # 간사가 되돌린 단계 (미실행이면 NULL)
    to_phase: Mapped[str | None] = mapped_column(String(30))
    # 간사가 삭제한 검토서 요청 예정일 (삭제 전 값. 미삭제면 NULL)
    cleared_due_date: Mapped[str | None] = mapped_column(String(10))

    requester_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    requester_name: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(Text)

    # 이 요청 이후 도서가 다시 접수된 시각.
    # 요청 목록에서 "도서가 다시 들어왔는지"를 보여주기 위한 표시이며,
    # 상태 전환(처리완료)은 간사가 직접 한다.
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
