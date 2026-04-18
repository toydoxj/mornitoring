"""검토 단계 모델 (예비검토, 1차보완, 2차보완, ...)"""

import enum
from datetime import datetime, date

from sqlalchemy import String, Integer, Boolean, Date, DateTime, Text, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class PhaseType(str, enum.Enum):
    PRELIMINARY = "preliminary"      # 예비검토
    SUPPLEMENT_1 = "supplement_1"    # 1차 보완
    SUPPLEMENT_2 = "supplement_2"    # 2차 보완
    SUPPLEMENT_3 = "supplement_3"    # 3차 보완
    SUPPLEMENT_4 = "supplement_4"    # 4차 보완
    SUPPLEMENT_5 = "supplement_5"    # 5차 보완


class ResultType(str, enum.Enum):
    PASS = "pass"                      # 적합
    SIMPLE_ERROR = "simple_error"      # 단순오류
    RECALCULATE = "recalculate"        # 재계산


class InappropriateDecision(str, enum.Enum):
    PENDING = "pending"                     # 대기 (기본값)
    CONFIRMED_SERIOUS = "confirmed_serious" # 확정(심각)
    CONFIRMED_SIMPLE = "confirmed_simple"   # 확정(단순)
    EXCLUDED = "excluded"                   # 제외 (확정됐다가 추후 제외 가능)


class ReviewStage(Base):
    __tablename__ = "review_stages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"))
    phase: Mapped[PhaseType] = mapped_column(Enum(PhaseType))
    phase_order: Mapped[int] = mapped_column(Integer)  # 0=예비, 1=1차, 2=2차...

    # 도서 배포
    doc_received_at: Mapped[date | None] = mapped_column(Date)       # 도서접수일
    doc_distributed_at: Mapped[date | None] = mapped_column(Date)    # 도서배포일
    # 검토서 요청 예정일 — 도서 접수 시점에 배정(기본 접수일 + 14일)되고
    # 검토위원 리마인드 알림의 기준일로 사용된다.
    report_due_date: Mapped[date | None] = mapped_column(Date)

    # 검토서 제출
    report_submitted_at: Mapped[date | None] = mapped_column(Date)   # 검토서 제출일
    reviewer_name: Mapped[str | None] = mapped_column(String(50))    # 검토자

    # 판정 결과
    result: Mapped[ResultType | None] = mapped_column(Enum(ResultType))
    review_opinion: Mapped[str | None] = mapped_column(Text)         # 검토의견
    defect_type_1: Mapped[str | None] = mapped_column(String(100))   # 부적합유형-1
    defect_type_2: Mapped[str | None] = mapped_column(String(100))   # 부적합유형-2
    defect_type_3: Mapped[str | None] = mapped_column(String(100))   # 부적합유형-3

    # 이의신청 (보완 라운드)
    objection_filed: Mapped[bool | None] = mapped_column(Boolean, default=False)
    objection_content: Mapped[str | None] = mapped_column(Text)      # 이의신청 검토내용
    objection_reason: Mapped[str | None] = mapped_column(Text)       # 이의신청 사유

    # 부적정 사례 검토 필요 여부 (업로드 시 검토자가 체크)
    inappropriate_review_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    # 부적합 검토 판정 (간사 이상이 결정)
    inappropriate_decision: Mapped[InappropriateDecision | None] = mapped_column(
        Enum(InappropriateDecision), default=None
    )
    # 부적합 판정에 대한 간사진 의견은 InappropriateNote 테이블에 다중 저장
    # (이전의 단일 inappropriate_note 컬럼은 제거)

    # 검토서 파일
    s3_file_key: Mapped[str | None] = mapped_column(String(500))     # S3 파일 경로

    # 비고
    stage_remarks: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 관계
    building = relationship("Building", back_populates="stages")
