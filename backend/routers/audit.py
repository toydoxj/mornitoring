"""감사 로그 조회 라우터"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.audit_log import AuditLog
from models.user import User, UserRole
from routers.auth import require_roles

router = APIRouter()


class AuditLogResponse(BaseModel):
    id: int
    user_id: int | None = None
    action: str
    target_type: str
    target_id: int | None = None
    before_data: dict | None = None
    after_data: dict | None = None
    ip_address: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int


@router.get("", response_model=AuditLogListResponse)
def list_audit_logs(
    action: str | None = None,
    target_type: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """감사 로그 목록 조회 (팀장/총괄간사만)"""
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)

    total = query.count()
    items = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return AuditLogListResponse(items=items, total=total)
