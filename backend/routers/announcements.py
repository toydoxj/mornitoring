"""공지사항 게시판 라우터"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.announcement import Announcement, AnnouncementComment
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles

router = APIRouter()


class CommentResponse(BaseModel):
    id: int
    announcement_id: int
    author_id: int
    author_name: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AnnouncementResponse(BaseModel):
    id: int
    author_id: int
    author_name: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    comment_count: int = 0

    model_config = {"from_attributes": True}


class AnnouncementDetailResponse(AnnouncementResponse):
    comments: list[CommentResponse] = []


class AnnouncementListResponse(BaseModel):
    items: list[AnnouncementResponse]
    total: int


class AnnouncementCreate(BaseModel):
    title: str
    content: str


class AnnouncementUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


class CommentCreate(BaseModel):
    content: str


# ---- 공지사항 목록/상세 ----

@router.get("", response_model=AnnouncementListResponse)
def list_announcements(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """공지사항 목록 (전체 로그인 사용자)"""
    from sqlalchemy import func as sa_func

    query = db.query(Announcement).order_by(Announcement.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()

    # 각 공지의 댓글 수
    ids = [a.id for a in items]
    count_map: dict[int, int] = {}
    if ids:
        rows = (
            db.query(AnnouncementComment.announcement_id, sa_func.count(AnnouncementComment.id))
            .filter(AnnouncementComment.announcement_id.in_(ids))
            .group_by(AnnouncementComment.announcement_id)
            .all()
        )
        count_map = {aid: cnt for aid, cnt in rows}

    return AnnouncementListResponse(
        items=[
            AnnouncementResponse(
                id=a.id,
                author_id=a.author_id,
                author_name=a.author_name,
                title=a.title,
                content=a.content,
                created_at=a.created_at,
                updated_at=a.updated_at,
                comment_count=count_map.get(a.id, 0),
            )
            for a in items
        ],
        total=total,
    )


@router.get("/{announcement_id}", response_model=AnnouncementDetailResponse)
def get_announcement(
    announcement_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ann = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    comments = [
        CommentResponse.model_validate(c) for c in ann.comments
    ]
    return AnnouncementDetailResponse(
        id=ann.id,
        author_id=ann.author_id,
        author_name=ann.author_name,
        title=ann.title,
        content=ann.content,
        created_at=ann.created_at,
        updated_at=ann.updated_at,
        comment_count=len(comments),
        comments=comments,
    )


# ---- 공지사항 작성/수정/삭제 (간사 이상) ----

@router.post("", response_model=AnnouncementResponse, status_code=201)
def create_announcement(
    body: AnnouncementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    title = (body.title or "").strip()
    content = (body.content or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목을 입력해주세요")
    if not content:
        raise HTTPException(status_code=400, detail="내용을 입력해주세요")

    ann = Announcement(
        author_id=current_user.id,
        author_name=current_user.name,
        title=title,
        content=content,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return AnnouncementResponse(
        id=ann.id,
        author_id=ann.author_id,
        author_name=ann.author_name,
        title=ann.title,
        content=ann.content,
        created_at=ann.created_at,
        updated_at=ann.updated_at,
        comment_count=0,
    )


@router.patch("/{announcement_id}", response_model=AnnouncementResponse)
def update_announcement(
    announcement_id: int,
    body: AnnouncementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    ann = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    is_owner = ann.author_id == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다")
    if body.title is not None:
        ann.title = body.title.strip()
    if body.content is not None:
        ann.content = body.content.strip()
    db.commit()
    db.refresh(ann)
    return AnnouncementResponse(
        id=ann.id,
        author_id=ann.author_id,
        author_name=ann.author_name,
        title=ann.title,
        content=ann.content,
        created_at=ann.created_at,
        updated_at=ann.updated_at,
        comment_count=len(ann.comments),
    )


@router.delete("/{announcement_id}", status_code=204)
def delete_announcement(
    announcement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    ann = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    is_owner = ann.author_id == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")
    db.delete(ann)
    db.commit()


# ---- 댓글 ----

@router.post("/{announcement_id}/comments", response_model=CommentResponse, status_code=201)
def create_comment(
    announcement_id: int,
    body: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """댓글 작성 (모든 로그인 사용자)"""
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="내용을 입력해주세요")
    ann = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    comment = AnnouncementComment(
        announcement_id=announcement_id,
        author_id=current_user.id,
        author_name=current_user.name,
        content=content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """댓글 삭제 (본인 또는 팀장/총괄간사)"""
    c = db.query(AnnouncementComment).filter(AnnouncementComment.id == comment_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다")
    is_owner = c.author_id == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")
    db.delete(c)
    db.commit()
