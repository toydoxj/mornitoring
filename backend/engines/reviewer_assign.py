"""검토위원 배정 엑셀 처리 엔진

엑셀 형식:
- A열: 관리번호
- B열: 검토위원 이름
"""

from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole


def preview_assignment(file_path: str | Path, db: Session) -> dict:
    """배정 엑셀을 미리보기 (변경사항 확인용)

    Returns:
        {
            "changes": [
                {
                    "mgmt_no": "2025-0001",
                    "reviewer_name": "홍길동",
                    "current_reviewer": "김철수" or null,
                    "status": "new" | "changed" | "same" | "not_found" | "reviewer_not_found"
                },
                ...
            ],
            "summary": {"new": 0, "changed": 0, "same": 0, "not_found": 0, "reviewer_not_found": 0}
        }
    """
    wb = load_workbook(str(file_path), data_only=True, read_only=True)
    ws = wb.active

    changes = []
    summary = {"new": 0, "changed": 0, "same": 0, "not_found": 0, "reviewer_not_found": 0}

    for row in ws.iter_rows(min_row=2):  # 1행은 헤더
        mgmt_no_cell = row[0].value
        reviewer_name_cell = row[1].value if len(row) > 1 else None

        if not mgmt_no_cell or not reviewer_name_cell:
            continue

        mgmt_no = str(mgmt_no_cell).strip()
        reviewer_name = str(reviewer_name_cell).strip()

        # 건축물 조회
        building = db.query(Building).filter(Building.mgmt_no == mgmt_no).first()
        if not building:
            changes.append({
                "mgmt_no": mgmt_no,
                "reviewer_name": reviewer_name,
                "current_reviewer": None,
                "status": "not_found",
            })
            summary["not_found"] += 1
            continue

        # 검토위원 조회 (이름으로)
        user = db.query(User).filter(
            User.name == reviewer_name,
            User.role == UserRole.REVIEWER,
        ).first()

        if not user:
            # 현재 배정된 검토위원 이름
            current_name = None
            if building.reviewer and building.reviewer.user:
                current_name = building.reviewer.user.name

            changes.append({
                "mgmt_no": mgmt_no,
                "reviewer_name": reviewer_name,
                "current_reviewer": current_name,
                "status": "reviewer_not_found",
            })
            summary["reviewer_not_found"] += 1
            continue

        # 현재 배정 상태 확인
        current_name = None
        if building.reviewer and building.reviewer.user:
            current_name = building.reviewer.user.name

        if current_name == reviewer_name:
            status = "same"
        elif current_name:
            status = "changed"
        else:
            status = "new"

        changes.append({
            "mgmt_no": mgmt_no,
            "reviewer_name": reviewer_name,
            "current_reviewer": current_name,
            "status": status,
        })
        summary[status] += 1

    wb.close()
    return {"changes": changes, "summary": summary}


def apply_assignment(file_path: str | Path, db: Session) -> dict:
    """배정 엑셀을 실제 적용

    Returns:
        {"applied": int, "skipped": int, "errors": list[str]}
    """
    wb = load_workbook(str(file_path), data_only=True, read_only=True)
    ws = wb.active

    applied = 0
    skipped = 0
    errors = []

    for row in ws.iter_rows(min_row=2):
        mgmt_no_cell = row[0].value
        reviewer_name_cell = row[1].value if len(row) > 1 else None

        if not mgmt_no_cell or not reviewer_name_cell:
            continue

        mgmt_no = str(mgmt_no_cell).strip()
        reviewer_name = str(reviewer_name_cell).strip()

        building = db.query(Building).filter(Building.mgmt_no == mgmt_no).first()
        if not building:
            errors.append(f"{mgmt_no}: 관리번호를 찾을 수 없습니다")
            skipped += 1
            continue

        user = db.query(User).filter(
            User.name == reviewer_name,
            User.role == UserRole.REVIEWER,
        ).first()

        if not user:
            errors.append(f"{mgmt_no}: 검토위원 '{reviewer_name}'을 찾을 수 없습니다")
            skipped += 1
            continue

        # Reviewer 레코드 확인/생성
        reviewer = db.query(Reviewer).filter(Reviewer.user_id == user.id).first()
        if not reviewer:
            reviewer = Reviewer(user_id=user.id)
            db.add(reviewer)
            db.flush()

        building.reviewer_id = reviewer.id
        applied += 1

    db.commit()
    wb.close()
    return {"applied": applied, "skipped": skipped, "errors": errors}
