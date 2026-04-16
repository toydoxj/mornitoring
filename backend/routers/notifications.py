"""알림 로그 조회 라우터"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.notification_log import NotificationLog
from models.user import User, UserRole
from routers.auth import require_roles

router = APIRouter()


class NotificationResponse(BaseModel):
    id: int
    recipient_id: int | None = None
    channel: str
    template_type: str
    title: str
    message: str | None = None
    is_sent: bool
    sent_at: datetime | None = None
    retry_count: int
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    is_sent: bool | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """알림 로그 목록 조회"""
    query = db.query(NotificationLog)

    if is_sent is not None:
        query = query.filter(NotificationLog.is_sent == is_sent)

    total = query.count()
    items = (
        query.order_by(NotificationLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return NotificationListResponse(items=items, total=total)
