"""부적합 대상 검토 판정에 대한 간사진 의견 (다중 작성자)"""

from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class InappropriateNote(Base):
    __tablename__ = "inappropriate_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("review_stages.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author_name: Mapped[str] = mapped_column(String(50))   # 작성 시점 이름 스냅샷
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
