"""감사 로그 조회 라우터"""

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.audit_log import AuditLog
from models.user import User, UserRole
from routers.auth import require_roles

logger = logging.getLogger(__name__)

router = APIRouter()

# 로그인 이력 페이지에 노출하는 action 화이트리스트.
# DB에는 더 다양한 action이 있지만 이 페이지는 인증 이벤트만 다룬다.
LOGIN_ACTIONS = ("login", "login_failed")


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


class LoginLogItem(BaseModel):
    id: int
    user_id: int | None = None
    user_name: str | None = None
    user_email: str | None = None
    action: str            # "login" | "login_failed"
    provider: str | None = None  # "password" | "kakao" | "kakao_link"
    failure_reason: str | None = None  # login_failed 한정
    attempted_email: str | None = None  # login_failed 한정 (user_id 없을 때 식별용)
    ip_address: str | None = None
    created_at: datetime


class LoginLogListResponse(BaseModel):
    items: list[LoginLogItem]
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


@router.get("/logins", response_model=LoginLogListResponse)
def list_login_logs(
    status: Literal["all", "success", "failed"] = "all",
    q: str | None = Query(None, description="사용자 이름/이메일 부분 검색"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """로그인/로그인 실패 이력 조회 (팀장/총괄간사만).

    - status: all=둘 다, success=login, failed=login_failed
    - q: user.name/user.email LIKE 검색 (실패 시 user 정보가 없을 수 있음)
    - 조회 자체도 감사 로그에 남긴다 (read_login_logs)
    """
    query = (
        db.query(AuditLog, User)
        .outerjoin(User, AuditLog.user_id == User.id)
    )

    if status == "success":
        query = query.filter(AuditLog.action == "login")
    elif status == "failed":
        query = query.filter(AuditLog.action == "login_failed")
    else:
        query = query.filter(AuditLog.action.in_(LOGIN_ACTIONS))

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(User.name.ilike(like), User.email.ilike(like)))

    total = query.count()
    rows = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items: list[LoginLogItem] = []
    for log, user in rows:
        after = log.after_data or {}
        items.append(LoginLogItem(
            id=log.id,
            user_id=log.user_id,
            user_name=user.name if user else None,
            user_email=user.email if user else None,
            action=log.action,
            provider=after.get("provider"),
            failure_reason=after.get("reason") if log.action == "login_failed" else None,
            attempted_email=after.get("email") if log.action == "login_failed" else None,
            ip_address=log.ip_address,
            created_at=log.created_at,
        ))

    # 조회 행위 자체를 감사로그로 남긴다 (누가/언제 무슨 필터로 봤는지).
    # 기록 실패가 응답을 깨뜨리면 안 되므로 best-effort.
    try:
        db.add(AuditLog(
            user_id=current_user.id,
            action="read_login_logs",
            target_type="audit_log",
            target_id=None,
            after_data={"status": status, "q": q, "page": page, "size": size, "count": len(items)},
        ))
        db.commit()
    except Exception:
        logger.exception("read_login_logs 감사 기록 실패")
        db.rollback()

    return LoginLogListResponse(items=items, total=total)
