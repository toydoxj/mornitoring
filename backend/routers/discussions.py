"""토론방 게시판 라우터 (전체 사용자 작성 가능)"""

import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import stream_upload_to_tempfile
from models.discussion import (
    Discussion,
    DiscussionComment,
    DiscussionAttachment,
    DiscussionCommentAttachment,
)
from models.user import User, UserRole
from routers.auth import get_current_user
from services.s3_storage import (
    upload_generic_file,
    get_download_url,
    delete_file as s3_delete_file,
)

router = APIRouter()


class AttachmentResponse(BaseModel):
    id: int
    discussion_id: int
    filename: str
    file_size: int
    content_type: str | None = None
    uploaded_by: int
    created_at: datetime
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
    discussion_id: int
    author_id: int
    author_name: str
    content: str
    created_at: datetime
    attachments: list[CommentAttachmentResponse] = []

    model_config = {"from_attributes": True}


def _attachment_to_response(att: DiscussionAttachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=att.id,
        discussion_id=att.discussion_id,
        filename=att.filename,
        file_size=att.file_size,
        content_type=att.content_type,
        uploaded_by=att.uploaded_by,
        created_at=att.created_at,
        download_url=get_download_url(att.s3_key),
    )


def _comment_attachment_to_response(
    att: DiscussionCommentAttachment,
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
    comment: DiscussionComment,
    attachments: list[DiscussionCommentAttachment],
) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        discussion_id=comment.discussion_id,
        author_id=comment.author_id,
        author_name=comment.author_name,
        content=comment.content,
        created_at=comment.created_at,
        attachments=[_comment_attachment_to_response(a) for a in attachments],
    )


class DiscussionResponse(BaseModel):
    id: int
    author_id: int
    author_name: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    comment_count: int = 0


class DiscussionDetailResponse(DiscussionResponse):
    comments: list[CommentResponse] = []
    attachments: list[AttachmentResponse] = []


class DiscussionListResponse(BaseModel):
    items: list[DiscussionResponse]
    total: int


class DiscussionCreate(BaseModel):
    title: str
    content: str


class DiscussionUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


class CommentCreate(BaseModel):
    content: str


# ---- 목록/상세 ----

@router.get("", response_model=DiscussionListResponse)
def list_discussions(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from sqlalchemy import func as sa_func

    query = db.query(Discussion).order_by(Discussion.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()

    ids = [d.id for d in items]
    count_map: dict[int, int] = {}
    if ids:
        rows = (
            db.query(DiscussionComment.discussion_id, sa_func.count(DiscussionComment.id))
            .filter(DiscussionComment.discussion_id.in_(ids))
            .group_by(DiscussionComment.discussion_id)
            .all()
        )
        count_map = {did: cnt for did, cnt in rows}

    return DiscussionListResponse(
        items=[
            DiscussionResponse(
                id=d.id,
                author_id=d.author_id,
                author_name=d.author_name,
                title=d.title,
                content=d.content,
                created_at=d.created_at,
                updated_at=d.updated_at,
                comment_count=count_map.get(d.id, 0),
            )
            for d in items
        ],
        total=total,
    )


@router.get("/{discussion_id}", response_model=DiscussionDetailResponse)
def get_discussion(
    discussion_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    d = db.query(Discussion).filter(Discussion.id == discussion_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="토론글을 찾을 수 없습니다")

    attachments = (
        db.query(DiscussionAttachment)
        .filter(DiscussionAttachment.discussion_id == d.id)
        .order_by(DiscussionAttachment.created_at)
        .all()
    )

    comment_ids = [c.id for c in d.comments]
    comment_attachment_map: dict[int, list[DiscussionCommentAttachment]] = {}
    if comment_ids:
        rows = (
            db.query(DiscussionCommentAttachment)
            .filter(DiscussionCommentAttachment.comment_id.in_(comment_ids))
            .order_by(DiscussionCommentAttachment.created_at)
            .all()
        )
        for a in rows:
            comment_attachment_map.setdefault(a.comment_id, []).append(a)

    return DiscussionDetailResponse(
        id=d.id,
        author_id=d.author_id,
        author_name=d.author_name,
        title=d.title,
        content=d.content,
        created_at=d.created_at,
        updated_at=d.updated_at,
        comment_count=len(d.comments),
        comments=[
            _comment_to_response(c, comment_attachment_map.get(c.id, []))
            for c in d.comments
        ],
        attachments=[_attachment_to_response(a) for a in attachments],
    )


# ---- 작성/수정/삭제 (모든 로그인 사용자 작성, 본인 또는 팀장/총괄간사 수정·삭제) ----

@router.post("", response_model=DiscussionResponse, status_code=201)
def create_discussion(
    body: DiscussionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    title = (body.title or "").strip()
    content = (body.content or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목을 입력해주세요")
    if not content:
        raise HTTPException(status_code=400, detail="내용을 입력해주세요")

    d = Discussion(
        author_id=current_user.id,
        author_name=current_user.name,
        title=title,
        content=content,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return DiscussionResponse(
        id=d.id, author_id=d.author_id, author_name=d.author_name,
        title=d.title, content=d.content,
        created_at=d.created_at, updated_at=d.updated_at, comment_count=0,
    )


@router.patch("/{discussion_id}", response_model=DiscussionResponse)
def update_discussion(
    discussion_id: int,
    body: DiscussionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = db.query(Discussion).filter(Discussion.id == discussion_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="토론글을 찾을 수 없습니다")
    is_owner = d.author_id == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다")
    if body.title is not None:
        d.title = body.title.strip()
    if body.content is not None:
        d.content = body.content.strip()
    db.commit()
    db.refresh(d)
    return DiscussionResponse(
        id=d.id, author_id=d.author_id, author_name=d.author_name,
        title=d.title, content=d.content,
        created_at=d.created_at, updated_at=d.updated_at,
        comment_count=len(d.comments),
    )


@router.delete("/{discussion_id}", status_code=204)
def delete_discussion(
    discussion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = db.query(Discussion).filter(Discussion.id == discussion_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="토론글을 찾을 수 없습니다")
    is_owner = d.author_id == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")
    db.delete(d)
    db.commit()


# ---- 댓글 ----

@router.post("/{discussion_id}/comments", response_model=CommentResponse, status_code=201)
def create_comment(
    discussion_id: int,
    body: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="내용을 입력해주세요")
    d = db.query(Discussion).filter(Discussion.id == discussion_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="토론글을 찾을 수 없습니다")
    c = DiscussionComment(
        discussion_id=discussion_id,
        author_id=current_user.id,
        author_name=current_user.name,
        content=content,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _comment_to_response(c, [])


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    c = db.query(DiscussionComment).filter(DiscussionComment.id == comment_id).first()
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
    "/{discussion_id}/attachments",
    response_model=AttachmentResponse,
    status_code=201,
)
async def upload_attachment(
    discussion_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = db.query(Discussion).filter(Discussion.id == discussion_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="토론글을 찾을 수 없습니다")
    is_owner = d.author_id == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="첨부파일 업로드 권한이 없습니다")

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다")

    suffix = Path(file.filename).suffix
    tmp_path = await stream_upload_to_tempfile(file, max_mb=20, suffix=suffix)
    try:
        unique = uuid.uuid4().hex[:8]
        s3_key = f"discussions/{discussion_id}/{unique}_{file.filename}"
        resolved_type = file.content_type or "application/octet-stream"
        upload_generic_file(tmp_path, s3_key, content_type=resolved_type)
        att = DiscussionAttachment(
            discussion_id=discussion_id,
            filename=file.filename,
            s3_key=s3_key,
            file_size=tmp_path.stat().st_size,
            content_type=resolved_type,
            uploaded_by=current_user.id,
        )
        db.add(att)
        db.commit()
        db.refresh(att)
        return _attachment_to_response(att)
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    att = db.query(DiscussionAttachment).filter(
        DiscussionAttachment.id == attachment_id
    ).first()
    if not att:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다")
    return {"download_url": get_download_url(att.s3_key), "filename": att.filename}


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
    """토론 댓글 첨부 업로드."""
    comment = (
        db.query(DiscussionComment)
        .filter(DiscussionComment.id == comment_id)
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
            f"discussions/{comment.discussion_id}/comments/"
            f"{comment_id}/{unique}_{file.filename}"
        )
        resolved_type = file.content_type or "application/octet-stream"
        upload_generic_file(tmp_path, s3_key, content_type=resolved_type)

        att = DiscussionCommentAttachment(
            comment_id=comment_id,
            filename=file.filename,
            s3_key=s3_key,
            file_size=tmp_path.stat().st_size,
            content_type=resolved_type,
            uploaded_by=current_user.id,
        )
        db.add(att)
        db.commit()
        db.refresh(att)
        return _comment_attachment_to_response(att)
    finally:
        tmp_path.unlink(missing_ok=True)


@router.delete("/comment-attachments/{attachment_id}", status_code=204)
def delete_comment_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    att = (
        db.query(DiscussionCommentAttachment)
        .filter(DiscussionCommentAttachment.id == attachment_id)
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
        db.query(DiscussionCommentAttachment)
        .filter(DiscussionCommentAttachment.id == attachment_id)
        .first()
    )
    if not att:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다")
    return {"download_url": get_download_url(att.s3_key), "filename": att.filename}


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    att = db.query(DiscussionAttachment).filter(
        DiscussionAttachment.id == attachment_id
    ).first()
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
