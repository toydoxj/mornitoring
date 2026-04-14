"""건축물 모델 (통합관리대장 A~AD열 매핑)"""

from datetime import datetime

from sqlalchemy import String, Boolean, Numeric, Integer, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # A: 모니터링 관리번호
    mgmt_no: Mapped[str] = mapped_column(String(20), unique=True, index=True)

    # B: 검토위원 (FK → reviewers)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("reviewers.id"))

    # C~AD: 대상 건축물 개요
    building_type: Mapped[str | None] = mapped_column(String(50))       # 건축구분
    sido: Mapped[str | None] = mapped_column(String(20))                # 시도명
    sigungu: Mapped[str | None] = mapped_column(String(30))             # 시군구명
    beopjeongdong: Mapped[str | None] = mapped_column(String(50))       # 법정동명
    land_type: Mapped[str | None] = mapped_column(String(20))           # 대지구분
    main_lot_no: Mapped[str | None] = mapped_column(String(10))         # 본번
    sub_lot_no: Mapped[str | None] = mapped_column(String(10))          # 부번
    special_lot_no: Mapped[str | None] = mapped_column(String(20))      # 특수지번
    building_name: Mapped[str | None] = mapped_column(String(200))      # 건물명
    main_structure: Mapped[str | None] = mapped_column(String(100))     # 주구조
    other_structure: Mapped[str | None] = mapped_column(String(200))    # 기타구조
    main_usage: Mapped[str | None] = mapped_column(String(100))         # 주용도
    other_usage: Mapped[str | None] = mapped_column(String(200))        # 기타용도
    gross_area: Mapped[float | None] = mapped_column(Numeric(12, 2))    # 연면적(㎡)
    height: Mapped[float | None] = mapped_column(Numeric(8, 2))         # 높이(m)
    floors_above: Mapped[int | None] = mapped_column(Integer)           # 지상층수
    floors_below: Mapped[int | None] = mapped_column(Integer)           # 지하층수
    is_special_structure: Mapped[bool | None] = mapped_column(Boolean)  # 특수구조물 여부
    is_high_rise: Mapped[bool | None] = mapped_column(Boolean)          # 고층 여부
    is_multi_use: Mapped[bool | None] = mapped_column(Boolean)          # 다중이용건축물 여부
    remarks: Mapped[str | None] = mapped_column(Text)                   # 비고
    architect_firm: Mapped[str | None] = mapped_column(String(100))     # 건축사(소속)
    architect_name: Mapped[str | None] = mapped_column(String(50))      # 건축사(성명)
    struct_eng_firm: Mapped[str | None] = mapped_column(String(100))    # 책임구조기술자(소속)
    struct_eng_name: Mapped[str | None] = mapped_column(String(50))     # 책임구조기술자(성명)
    high_risk_type: Mapped[str | None] = mapped_column(String(100))     # 고위험유형
    related_tech_coop: Mapped[bool | None] = mapped_column(Boolean)     # 관계기술자 협력대상 여부
    drawing_creation: Mapped[bool | None] = mapped_column(Boolean)      # 관계기술자 도면작성 여부

    # 현재 진행 단계
    current_phase: Mapped[str | None] = mapped_column(String(30))       # 예비/1차/2차...
    final_result: Mapped[str | None] = mapped_column(String(30))        # 최종 판정결과

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 관계
    reviewer = relationship("Reviewer", back_populates="buildings")
    stages = relationship("ReviewStage", back_populates="building", order_by="ReviewStage.phase_order")
