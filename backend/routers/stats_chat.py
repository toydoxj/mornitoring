"""통계 분석 챗봇 라우터.

통계자료 화면에서 자연어로 질문하면 LLM이 읽기 전용 SELECT 를 만들어 실제 DB를
조회하고, 근거와 함께 답한다. 접근 권한은 통계자료 화면(`/api/buildings/stats`)과
동일하게 팀장·총괄간사·간사·관리원으로 한정한다(검토위원 제외).

주의: 답변은 StreamingResponse 로 흘려보내므로, 스트리밍 도중에는
`Depends(get_db)` 세션을 쓸 수 없다(FastAPI가 응답 전에 정리함). 생성기 안에서는
별도 세션(SessionLocal)을 직접 열고 닫는다.
"""

import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal, get_db
from models.stats_chat import StatsChatConversation, StatsChatMessage, StatsChatRole
from models.user import User, UserRole
from routers.auth import require_roles
from services import stats_chat
from services.stats_chat import RateLimited, StatsChatUnavailable, sse_frame

logger = logging.getLogger(__name__)

router = APIRouter()

# 통계자료 화면과 동일한 접근 범위 (검토위원 제외)
STATS_CHAT_ROLES = (
    UserRole.TEAM_LEADER,
    UserRole.CHIEF_SECRETARY,
    UserRole.SECRETARY,
    UserRole.MANAGER,
)

TITLE_MAX_LENGTH = 120


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None
    # 화면에서 적용 중인 필터(예: "배포차수: 3차수") — 프롬프트에만 쓰인다.
    screen_context: str | None = Field(default=None, max_length=500)


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    sql_log: list[dict] = []
    created_at: str


class ConversationResponse(BaseModel):
    id: int
    title: str
    updated_at: str


class ConversationDetailResponse(BaseModel):
    id: int
    title: str
    messages: list[MessageResponse]


def _parse_sql_log(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _to_message_response(message: StatsChatMessage) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        role=message.role.value if hasattr(message.role, "value") else str(message.role),
        content=message.content,
        sql_log=_parse_sql_log(message.sql_log),
        created_at=message.created_at.isoformat() if message.created_at else "",
    )


def _owned_conversation(
    db: Session, conversation_id: int, user: User
) -> StatsChatConversation:
    conversation = (
        db.query(StatsChatConversation)
        .filter(
            StatsChatConversation.id == conversation_id,
            StatsChatConversation.user_id == user.id,
        )
        .one_or_none()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")
    return conversation


@router.get("/status")
def chat_status(
    current_user: User = Depends(require_roles(*STATS_CHAT_ROLES)),
):
    """챗봇 사용 가능 여부. 프론트는 enabled=false면 버튼을 숨긴다."""
    return {"enabled": stats_chat.is_enabled(), "model": settings.openai_model}


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STATS_CHAT_ROLES)),
):
    """내 대화 목록 (최신순 20건)."""
    rows = (
        db.query(StatsChatConversation)
        .filter(StatsChatConversation.user_id == current_user.id)
        .order_by(StatsChatConversation.updated_at.desc())
        .limit(20)
        .all()
    )
    return [
        ConversationResponse(
            id=row.id,
            title=row.title,
            updated_at=row.updated_at.isoformat() if row.updated_at else "",
        )
        for row in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STATS_CHAT_ROLES)),
):
    conversation = _owned_conversation(db, conversation_id, current_user)
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        messages=[_to_message_response(m) for m in conversation.messages],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STATS_CHAT_ROLES)),
):
    conversation = _owned_conversation(db, conversation_id, current_user)
    db.delete(conversation)
    db.commit()


@router.post("/ask")
def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STATS_CHAT_ROLES)),
):
    """질문을 받아 SSE 로 답변을 스트리밍한다.

    스트림 이벤트: status / sql / delta / done / error
    """
    if not stats_chat.is_enabled():
        raise HTTPException(
            status_code=503, detail="AI 분석 기능이 설정되지 않았습니다(OPENAI_API_KEY)"
        )
    try:
        stats_chat.check_rate_limit(current_user.id)
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    question = payload.question.strip()
    conversation_id = payload.conversation_id
    user_id = current_user.id

    # 대화·사용자 질문은 스트리밍 시작 전에 확정해 둔다.
    # 여기서 쓰는 세션은 인증(require_roles)이 쓴 것과 같은 세션이며, 응답이 다 나갈
    # 때까지 정리되지 않는다. 스트리밍이 길어지면 커넥션 풀이 마르므로 마지막에
    # 명시적으로 close() 해서 커넥션을 먼저 돌려준다.
    try:
        if conversation_id is None:
            conversation = StatsChatConversation(
                user_id=user_id, title=question[:TITLE_MAX_LENGTH]
            )
            db.add(conversation)
            db.flush()
        else:
            conversation = (
                db.query(StatsChatConversation)
                .filter(
                    StatsChatConversation.id == conversation_id,
                    StatsChatConversation.user_id == user_id,
                )
                .one_or_none()
            )
            if conversation is None:
                raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")
        conversation_id = conversation.id
        history = [
            (
                m.role.value if hasattr(m.role, "value") else str(m.role),
                m.content,
            )
            for m in conversation.messages
        ]
        db.add(
            StatsChatMessage(
                conversation_id=conversation_id,
                role=StatsChatRole.USER,
                content=question,
            )
        )
        db.commit()
    finally:
        db.close()

    async def event_stream() -> AsyncIterator[str]:
        content = ""
        sql_log: list[dict] = []
        input_tokens = output_tokens = 0
        error_message = ""
        started = time.perf_counter()
        try:
            generator = stats_chat.stream_answer(
                question=question,
                history=history,
                screen_context=payload.screen_context,
            )
            async for event_name, data in generator:
                if event_name == "final":
                    content = data.get("content", "")
                    sql_log = data.get("sql_log", [])
                    input_tokens = data.get("input_tokens", 0)
                    output_tokens = data.get("output_tokens", 0)
                    continue
                if event_name == "error":
                    # 오류로 끝난 답변을 정상 완료로 저장하면 이력이 왜곡된다.
                    error_message = str(data.get("message", "")) or "원인 미상"
                yield sse_frame(event_name, data)
        except StatsChatUnavailable as exc:
            yield sse_frame("error", {"message": str(exc)})
            return
        except Exception as exc:  # 스트림 중단 시에도 클라이언트에 사유를 남긴다
            logger.exception("stats_chat_stream_failed")
            yield sse_frame("error", {"message": f"분석 중 오류가 발생했습니다: {exc}"})
            return

        if error_message:
            # 부분 답변이 있으면 함께 남기고, 없으면 오류 자체를 본문으로 남긴다.
            content = (
                f"{content}\n\n오류: {error_message}".strip()
                if content
                else f"오류: {error_message}"
            )

        message_id = None
        save_db = SessionLocal()
        try:
            message = StatsChatMessage(
                conversation_id=conversation_id,
                role=StatsChatRole.ASSISTANT,
                content=content,
                sql_log=json.dumps(sql_log, ensure_ascii=False) if sql_log else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            save_db.add(message)
            # 대화 목록을 최신순으로 정렬하려면 스레드의 updated_at 도 함께 올린다.
            save_db.query(StatsChatConversation).filter(
                StatsChatConversation.id == conversation_id
            ).update({StatsChatConversation.updated_at: func.now()})
            save_db.commit()
            message_id = message.id
        except Exception:
            logger.exception("stats_chat_save_failed")
            save_db.rollback()
        finally:
            save_db.close()

        yield sse_frame(
            "done",
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "ok": not error_message,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 계열 프록시 버퍼링 방지
        },
    )
