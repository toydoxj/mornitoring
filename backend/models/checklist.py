"""상세체크리스트 의견 모델"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ChecklistOpinion(Base):
    __tablename__ = "checklist_opinions"
    __table_args__ = (
        Index("ix_checklist_opinions_item_key_created_at", "item_key", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    item_key: Mapped[str] = mapped_column(String(80), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    author_name: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
