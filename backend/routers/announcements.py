"""공지사항 게시판 라우터"""

import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import stream_upload_to_tempfile
from models.announcement import (
    Announcement,
    AnnouncementComment,
    AnnouncementAttachment,
    AnnouncementCommentAttachment,
)
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from services.s3_storage import (
    upload_generic_file,
    get_download_url,
    delete_file as s3_delete_file,
)

router = APIRouter()


class AttachmentResponse(BaseModel):
    id: int
    announcement_id: int
    filename: str
    file_size: int
    content_type: str | None = None
    uploaded_by: int
    created_at: datetime
    # 프론트에서 이미지 인라인 렌더 및 원클릭 다운로드에 사용 (presigned URL)
    download_url: str | None = None

    model_config = {"from_attributes": True}


class CommentAttachmentResponse(BaseModel):
    id: int
    comment_id: int
    filename: str
    file_size: int
    content_type: str | None = None
    uploaded_by: int
    created_at: datetime
    download_url: str | None = None

    model_config = {"from_attributes": True}


class CommentResponse(BaseModel):
    id: int
    announcement_id: int
    author_id: int
    author_name: str
    content: str
    created_at: datetime
    attachments: list[CommentAttachmentResponse] = []

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
    attachments: list[AttachmentResponse] = []


def _attachment_to_response(att: AnnouncementAttachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=att.id,
        announcement_id=att.announcement_id,
        filename=att.filename,
        file_size=att.file_size,
        content_type=att.content_type,
        uploaded_by=att.uploaded_by,
        created_at=att.created_at,
        download_url=get_download_url(att.s3_key),
    )


def _comment_attachment_to_response(
    att: AnnouncementCommentAttachment,
) -> CommentAttachmentResponse:
    return CommentAttachmentResponse(
        id=att.id,
        comment_id=att.comment_id,
        filename=att.filename,
        file_size=att.file_size,
        content_type=att.content_type,
        uploaded_by=att.uploaded_by,
        created_at=att.created_at,
        download_url=get_download_url(att.s3_key),
    )


def _comment_to_response(
    comment: AnnouncementComment,
    attachments: list[AnnouncementCommentAttachment],
) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        announcement_id=comment.announcement_id,
        author_id=comment.author_id,
        author_name=comment.author_name,
        content=comment.content,
        created_at=comment.created_at,
        attachments=[_comment_attachment_to_response(a) for a in attachments],
    )


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

    comment_ids = [c.id for c in ann.comments]
    comment_attachment_map: dict[int, list[AnnouncementCommentAttachment]] = {}
    if comment_ids:
        rows = (
            db.query(AnnouncementCommentAttachment)
            .filter(AnnouncementCommentAttachment.comment_id.in_(comment_ids))
            .order_by(AnnouncementCommentAttachment.created_at)
            .all()
        )
        for a in rows:
            comment_attachment_map.setdefault(a.comment_id, []).append(a)

    comments = [
        _comment_to_response(c, comment_attachment_map.get(c.id, []))
        for c in ann.comments
    ]
    attachments = (
        db.query(AnnouncementAttachment)
        .filter(AnnouncementAttachment.announcement_id == ann.id)
        .order_by(AnnouncementAttachment.created_at)
        .all()
    )
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
        attachments=[_attachment_to_response(a) for a in attachments],
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
    return _comment_to_response(comment, [])


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


# ---- 첨부파일 ----

@router.post(
    "/{announcement_id}/attachments",
    response_model=AttachmentResponse,
    status_code=201,
)
async def upload_attachment(
    announcement_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """첨부파일 업로드 (공지 작성자 또는 팀장/총괄간사)"""
    ann = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    is_owner = ann.author_id == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="첨부파일 업로드 권한이 없습니다")

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다")

    # 임시 저장 후 S3 업로드 — 메모리 stream으로 직접 tempfile에 기록
    suffix = Path(file.filename).suffix
    tmp_path = await stream_upload_to_tempfile(file, max_mb=20, suffix=suffix)

    try:
        unique = uuid.uuid4().hex[:8]
        s3_key = f"announcements/{announcement_id}/{unique}_{file.filename}"
        resolved_type = file.content_type or "application/octet-stream"
        upload_generic_file(
            tmp_path, s3_key,
            content_type=resolved_type,
        )

        attachment = AnnouncementAttachment(
            announcement_id=announcement_id,
            filename=file.filename,
            s3_key=s3_key,
            file_size=tmp_path.stat().st_size,
            content_type=resolved_type,
            uploaded_by=current_user.id,
        )
        db.add(attachment)
        db.commit()
        db.refresh(attachment)
        return _attachment_to_response(attachment)
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """첨부파일 다운로드 URL 반환 (presigned)"""
    att = db.query(AnnouncementAttachment).filter(
        AnnouncementAttachment.id == attachment_id
    ).first()
    if not att:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다")
    url = get_download_url(att.s3_key)
    return {"download_url": url, "filename": att.filename}


# ---- 댓글 첨부파일 (모든 로그인 사용자 업로드, 업로더 본인 + 팀장/총괄간사 삭제) ----

@router.post(
    "/comments/{comment_id}/attachments",
    response_model=CommentAttachmentResponse,
    status_code=201,
)
async def upload_comment_attachment(
    comment_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """공지 댓글 첨부 업로드."""
    comment = (
        db.query(AnnouncementComment)
        .filter(AnnouncementComment.id == comment_id)
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다")
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다")

    suffix = Path(file.filename).suffix
    tmp_path = await stream_upload_to_tempfile(file, max_mb=20, suffix=suffix)
    try:
        unique = uuid.uuid4().hex[:8]
        s3_key = (
            f"announcements/{comment.announcement_id}/comments/"
            f"{comment_id}/{unique}_{file.filename}"
        )
        resolved_type = file.content_type or "application/octet-stream"
        upload_generic_file(tmp_path, s3_key, content_type=resolved_type)

        attachment = AnnouncementCommentAttachment(
            comment_id=comment_id,
            filename=file.filename,
            s3_key=s3_key,
            file_size=tmp_path.stat().st_size,
            content_type=resolved_type,
            uploaded_by=current_user.id,
        )
        db.add(attachment)
        db.commit()
        db.refresh(attachment)
        return _comment_attachment_to_response(attachment)
    finally:
        tmp_path.unlink(missing_ok=True)


@router.delete("/comment-attachments/{attachment_id}", status_code=204)
def delete_comment_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """댓글 첨부 삭제 (업로더 본인 + 팀장/총괄간사)."""
    att = (
        db.query(AnnouncementCommentAttachment)
        .filter(AnnouncementCommentAttachment.id == attachment_id)
        .first()
    )
    if not att:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다")
    is_owner = att.uploaded_by == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")
    try:
        s3_delete_file(att.s3_key)
    except Exception:
        pass
    db.delete(att)
    db.commit()


@router.get("/comment-attachments/{attachment_id}/download")
def download_comment_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    att = (
        db.query(AnnouncementCommentAttachment)
        .filter(AnnouncementCommentAttachment.id == attachment_id)
        .first()
    )
    if not att:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다")
    return {"download_url": get_download_url(att.s3_key), "filename": att.filename}


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """첨부파일 삭제 (업로더 본인 또는 팀장/총괄간사)"""
    att = db.query(AnnouncementAttachment).filter(
        AnnouncementAttachment.id == attachment_id
    ).first()
    if not att:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다")
    is_owner = att.uploaded_by == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")

    # S3 파일 삭제 (실패해도 DB는 지움)
    try:
        s3_delete_file(att.s3_key)
    except Exception:
        pass
    db.delete(att)
    db.commit()
