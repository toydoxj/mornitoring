"""사용자 관리 라우터"""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from openpyxl import load_workbook
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import get_current_user, get_password_hash, require_roles

router = APIRouter()

DEFAULT_PASSWORD = "ksea"

ROLE_MAP = {
    "팀장": UserRole.TEAM_LEADER,
    "총괄간사": UserRole.CHIEF_SECRETARY,
    "간사": UserRole.SECRETARY,
    "검토위원": UserRole.REVIEWER,
    "team_leader": UserRole.TEAM_LEADER,
    "chief_secretary": UserRole.CHIEF_SECRETARY,
    "secretary": UserRole.SECRETARY,
    "reviewer": UserRole.REVIEWER,
}


# --- Pydantic 스키마 ---

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


@router.post("/import-excel")
async def import_users_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 일괄 등록 (엑셀)

    엑셀 형식: A열=이름, B열=이메일, C열=역할(팀장/총괄간사/간사/검토위원), D열=전화번호(선택)
    """
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="엑셀 파일(.xlsx)만 업로드 가능합니다")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        wb = load_workbook(str(tmp_path), data_only=True, read_only=True)
        ws = wb.active

        created = 0
        skipped = 0
        errors = []

        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
            name = str(row[0].value).strip() if row[0].value else None
            email = str(row[1].value).strip() if len(row) > 1 and row[1].value else None
            role_str = str(row[2].value).strip() if len(row) > 2 and row[2].value else None
            phone = str(row[3].value).strip() if len(row) > 3 and row[3].value else None

            if not name or not email:
                continue

            # 역할 매핑
            role = ROLE_MAP.get(role_str, UserRole.REVIEWER) if role_str else UserRole.REVIEWER

            # 중복 체크
            if db.query(User).filter(User.email == email).first():
                skipped += 1
                continue

            user = User(
                name=name,
                email=email,
                role=role,
                phone=phone,
                password_hash=get_password_hash(DEFAULT_PASSWORD),
                must_change_password=True,
            )
            db.add(user)
            created += 1

        db.commit()
        wb.close()
        return {"created": created, "skipped": skipped, "errors": errors}

    finally:
        tmp_path.unlink(missing_ok=True)


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
