"""문의사항 모델"""

import enum
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class InquiryStatus(str, enum.Enum):
    OPEN = "open"                    # 접수
    ASKING_AGENCY = "asking_agency"  # 관리원문의중
    COMPLETED = "completed"          # 완료
    NEXT_PHASE = "next_phase"        # 다음단계


class Inquiry(Base):
    __tablename__ = "inquiries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"))
    mgmt_no: Mapped[str] = mapped_column(String(20))
    phase: Mapped[str] = mapped_column(String(30))
    # 작성자 식별 — 동명이인 위험을 피하기 위해 user_id를 권한 기준으로 사용.
    # 기존 데이터 호환을 위해 nullable, 신규 데이터는 항상 채워진다.
    submitter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    submitter_name: Mapped[str] = mapped_column(String(50))       # 표시용 (검토위원)
    content: Mapped[str] = mapped_column(Text)                     # 문의 내용
    reply: Mapped[str | None] = mapped_column(Text)                # 답변
    status: Mapped[InquiryStatus] = mapped_column(
        Enum(InquiryStatus), default=InquiryStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
