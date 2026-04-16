"""통합관리대장 엑셀 Import/Export 라우터"""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from engines.ledger_import import import_ledger
from engines.ledger_export import export_ledger

router = APIRouter()


@router.post("/import")
async def import_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """통합관리대장 엑셀 파일을 DB에 import"""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="엑셀 파일(.xlsx)만 업로드 가능합니다")

    # 임시 파일로 저장 후 처리
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = import_ledger(tmp_path, db)
        return result
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/export")
def export_excel(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """DB 데이터를 통합관리대장 형식의 엑셀로 export"""
    output = export_ledger(db)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=management_ledger.xlsx"},
    )
