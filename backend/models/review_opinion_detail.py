"""검토서 상세검토 내용 원문 모델."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ReviewOpinionDetail(Base):
    __tablename__ = "review_opinion_details"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("review_stages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    phase: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    phase_group: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    row_number: Mapped[int | None] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    quality_decision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="unsuitable",
        server_default="unsuitable",
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

    stage = relationship("ReviewStage", back_populates="opinion_details")
