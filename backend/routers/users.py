"""사용자 관리 라우터"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import get_current_user, get_password_hash, require_roles

router = APIRouter()


# --- Pydantic 스키마 ---

DEFAULT_PASSWORD = "ksea"


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    role: UserRole
    phone: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: UserRole
    phone: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int


# --- 엔드포인트 ---

@router.get("", response_model=UserListResponse)
def list_users(
    role: UserRole | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 목록 조회 (팀장/총괄간사만)"""
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)

    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return UserListResponse(items=items, total=total)


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 등록 (팀장/총괄간사만)"""
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다")

    user = User(
        name=body.name,
        email=body.email,
        role=body.role,
        phone=body.phone,
        password_hash=get_password_hash(DEFAULT_PASSWORD),
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """사용자 상세 조회"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 정보 수정 (팀장/총괄간사만)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 삭제 (팀장/총괄간사)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    # reviewer 연결 해제
    reviewer = db.query(Reviewer).filter(Reviewer.user_id == user.id).first()
    if reviewer:
        db.query(Building).filter(Building.reviewer_id == reviewer.id).update(
            {"reviewer_id": None}
        )
        db.delete(reviewer)

    db.delete(user)
    db.commit()


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """비밀번호 초기화 (팀장/총괄간사)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    user.password_hash = get_password_hash(DEFAULT_PASSWORD)
    user.must_change_password = True
    db.commit()
    return {"message": f"{user.name}의 비밀번호가 초기화되었습니다"}
