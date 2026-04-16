"""검토위원 배정 라우터"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import require_roles

router = APIRouter()


class AssignRequest(BaseModel):
    building_id: int
    reviewer_id: int


class ReviewerResponse(BaseModel):
    id: int
    user_id: int
    user_name: str
    group_no: str | None = None

    model_config = {"from_attributes": True}


@router.get("/reviewers")
def list_reviewers(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """검토위원 목록 조회"""
    reviewers = db.query(Reviewer).all()
    result = []
    for r in reviewers:
        result.append({
            "id": r.id,
            "user_id": r.user_id,
            "user_name": r.user.name if r.user else "",
            "group_no": r.group_no,
        })
    return result


@router.post("/assign")
def assign_reviewer(
    body: AssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """건축물에 검토위원 배정"""
    building = db.query(Building).filter(Building.id == body.building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    reviewer = db.query(Reviewer).filter(Reviewer.id == body.reviewer_id).first()
    if not reviewer:
        raise HTTPException(status_code=404, detail="검토위원을 찾을 수 없습니다")

    building.reviewer_id = reviewer.id
    db.commit()
    return {"message": f"관리번호 {building.mgmt_no}에 검토위원이 배정되었습니다"}


@router.delete("/assign/{building_id}")
def unassign_reviewer(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """건축물의 검토위원 배정 해제"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    building.reviewer_id = None
    db.commit()
    return {"message": "검토위원 배정이 해제되었습니다"}
