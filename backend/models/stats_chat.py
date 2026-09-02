"""통계 분석 챗봇 대화 이력 모델.

통계자료 화면의 분석 챗봇이 주고받은 질문·답변을 보관한다. 답변을 만들 때
실행된 SELECT 문과 조회 행수를 함께 남겨, 나중에 "이 수치가 어디서 나왔는지"를
사람이 그대로 재현·검증할 수 있게 한다.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class StatsChatRole(str, enum.Enum):
    USER = "user"            # 사용자 질문
    ASSISTANT = "assistant"  # 모델 답변


class StatsChatConversation(Base):
    """대화 스레드 1건 (사용자별)."""

    __tablename__ = "stats_chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 첫 질문에서 잘라낸 표시용 제목
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages = relationship(
        "StatsChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="StatsChatMessage.id",
    )


class StatsChatMessage(Base):
    """대화 메시지 1건.

    `sql_log` 는 어시스턴트 메시지에만 채워지며, 실행한 SELECT 목록을
    `[{"sql": ..., "row_count": n, "duration_ms": n, "error": null}]` 형태의
    JSON 문자열로 담는다. JSON 컬럼 대신 Text 를 쓰는 이유는 SQLite 기반
    테스트와 PostgreSQL 운영 환경에서 동일하게 동작시키기 위함이다.
    """

    __tablename__ = "stats_chat_messages"
    __table_args__ = (
        Index("ix_stats_chat_messages_conversation_id_id", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("stats_chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[StatsChatRole] = mapped_column(Enum(StatsChatRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sql_log: Mapped[str | None] = mapped_column(Text)
    # 사용량·성능 기록 (비용 추적용)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation = relationship("StatsChatConversation", back_populates="messages")
