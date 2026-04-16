"""통합관리대장 엑셀 Import/Export 라우터"""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from database import get_db
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from engines.ledger_import import import_ledger
from engines.ledger_import_2025 import import_ledger_2025
from engines.ledger_export import export_ledger

router = APIRouter()


def _detect_format(file_path: Path) -> str:
    """엑셀 파일의 시트 구조를 분석하여 import 방식 결정"""
    wb = load_workbook(str(file_path), data_only=True, read_only=True)
    sheet_names = wb.sheetnames
    wb.close()

    for sn in sheet_names:
        if "통합 관리대장" in sn:
            return "unified"
        if "관리대장" in sn and ("1차수" in sn or "2025" in sn or "1443" in sn):
            return "2025"
    # 기본값
    return "unified"


@router.post("/import")
async def import_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """통합관리대장 엑셀 파일을 DB에 import (형식 자동 감지)"""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="엑셀 파일(.xlsx)만 업로드 가능합니다")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        fmt = _detect_format(tmp_path)
        if fmt == "2025":
            result = import_ledger_2025(tmp_path, db)
        else:
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
