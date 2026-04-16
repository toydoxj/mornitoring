"""알림 발송 이력 모델"""

from datetime import datetime

from sqlalchemy import String, Boolean, Integer, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20))     # kakao / web
    template_type: Mapped[str] = mapped_column(String(50))  # doc_received / review_request / reminder
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str | None] = mapped_column(Text)
    related_building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"))
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
