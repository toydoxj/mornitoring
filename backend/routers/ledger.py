"""통합관리대장 엑셀 Import/Export 라우터"""

from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from database import get_db
from dependencies import stream_upload_to_tempfile
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from engines.ledger_import import import_ledger
from engines.ledger_import_2025 import import_ledger_2025
from engines.ledger_import_unified import import_ledger_unified
from engines.ledger_export import export_ledger

router = APIRouter()


def _detect_format(file_path: Path) -> str:
    """엑셀 파일의 시트 구조를 분석하여 import 방식 결정"""
    wb = load_workbook(str(file_path), data_only=True, read_only=True)
    sheet_names = wb.sheetnames

    has_unified = False
    has_2025 = False
    for sn in sheet_names:
        if "통합 관리대장" in sn:
            has_unified = True
            # 통합 관리대장 시트의 Row 4 A열 확인하여 신형/구형 구분
            ws = wb[sn]
            row4_a = ws.cell(row=4, column=1).value
            wb.close()
            if row4_a and "관리번호" in str(row4_a):
                return "unified_new"  # 3차수 통합본 (Row4 헤더, Row5 데이터)
            return "unified_old"      # 기존 형식 (Row2 헤더, Row3 데이터)
        if "관리대장" in sn and ("1차수" in sn or "1443" in sn):
            has_2025 = True

    wb.close()
    if has_2025:
        return "2025"
    return "unified_old"


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

    tmp_path = await stream_upload_to_tempfile(file, max_mb=20, suffix=".xlsx")  # 통합관리대장은 큼

    try:
        fmt = _detect_format(tmp_path)
        if fmt == "unified_new":
            result = import_ledger_unified(tmp_path, db)
        elif fmt == "2025":
            result = import_ledger_2025(tmp_path, db)
        else:
            result = import_ledger(tmp_path, db)
        return result
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/export")
def export_excel(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """DB 데이터를 통합관리대장 형식의 엑셀로 export (팀장/총괄간사/간사)"""
    output = export_ledger(db)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=management_ledger.xlsx"},
    )
