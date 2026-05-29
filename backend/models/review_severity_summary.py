"""검토서 분류별 심각도 집계 모델."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ReviewSeveritySummary(Base):
    __tablename__ = "review_severity_summaries"
    __table_args__ = (
        UniqueConstraint(
            "stage_id",
            "category",
            "severity",
            name="uq_review_severity_summary_stage_category_severity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("review_stages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    stage = relationship("ReviewStage", back_populates="severity_summaries")
