"""상세체크리스트 의견 라우터"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from database import get_db
from models.checklist import ChecklistOpinion
from models.user import User, UserRole
from routers.auth import get_current_user

router = APIRouter()


class ChecklistOpinionResponse(BaseModel):
    id: int
    item_key: str
    author_id: int
    author_name: str
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChecklistOpinionSummary(BaseModel):
    item_key: str
    count: int
    latest_at: datetime | None = None


class ChecklistOpinionCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ChecklistOpinionUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


def _normalize_item_key(item_key: str) -> str:
    normalized = item_key.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="체크리스트 항목이 필요합니다")
    if len(normalized) > 80:
        raise HTTPException(status_code=400, detail="체크리스트 항목 키가 너무 깁니다")
    return normalized


def _normalize_content(content: str) -> str:
    normalized = content.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="의견 내용을 입력해주세요")
    if len(normalized) > 2000:
        raise HTTPException(status_code=400, detail="의견은 2,000자 이내로 입력해주세요")
    return normalized


def _can_moderate(user: User) -> bool:
    return user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)


@router.get("/opinions/summary", response_model=list[ChecklistOpinionSummary])
def list_opinion_summaries(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = (
        db.query(
            ChecklistOpinion.item_key,
            sa_func.count(ChecklistOpinion.id),
            sa_func.max(ChecklistOpinion.created_at),
        )
        .group_by(ChecklistOpinion.item_key)
        .all()
    )
    return [
        ChecklistOpinionSummary(
            item_key=item_key,
            count=count,
            latest_at=latest_at,
        )
        for item_key, count, latest_at in rows
    ]


@router.get(
    "/items/{item_key}/opinions",
    response_model=list[ChecklistOpinionResponse],
)
def list_item_opinions(
    item_key: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    normalized_key = _normalize_item_key(item_key)
    return (
        db.query(ChecklistOpinion)
        .filter(ChecklistOpinion.item_key == normalized_key)
        .order_by(ChecklistOpinion.created_at.desc(), ChecklistOpinion.id.desc())
        .all()
    )


@router.post(
    "/items/{item_key}/opinions",
    response_model=ChecklistOpinionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_item_opinion(
    item_key: str,
    body: ChecklistOpinionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    normalized_key = _normalize_item_key(item_key)
    content = _normalize_content(body.content)
    opinion = ChecklistOpinion(
        item_key=normalized_key,
        author_id=current_user.id,
        author_name=current_user.name,
        content=content,
    )
    db.add(opinion)
    db.commit()
    db.refresh(opinion)
    return opinion


@router.patch("/opinions/{opinion_id}", response_model=ChecklistOpinionResponse)
def update_opinion(
    opinion_id: int,
    body: ChecklistOpinionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opinion = db.query(ChecklistOpinion).filter(ChecklistOpinion.id == opinion_id).first()
    if not opinion:
        raise HTTPException(status_code=404, detail="의견을 찾을 수 없습니다")
    if opinion.author_id != current_user.id and not _can_moderate(current_user):
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다")

    opinion.content = _normalize_content(body.content)
    db.commit()
    db.refresh(opinion)
    return opinion


@router.delete("/opinions/{opinion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_opinion(
    opinion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opinion = db.query(ChecklistOpinion).filter(ChecklistOpinion.id == opinion_id).first()
    if not opinion:
        raise HTTPException(status_code=404, detail="의견을 찾을 수 없습니다")
    if opinion.author_id != current_user.id and not _can_moderate(current_user):
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")

    db.delete(opinion)
    db.commit()
