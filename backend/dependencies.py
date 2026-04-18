"""공용 FastAPI 의존성/헬퍼."""

import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

# 업로드 크기 제한 (MB)
DEFAULT_MAX_UPLOAD_MB = 10        # 일반 파일 (엑셀/검토서 등)
ATTACHMENT_MAX_UPLOAD_MB = 20     # 공지/토론 첨부 (이미지 포함 가능성)
CHUNK_SIZE_BYTES = 1024 * 1024     # 1MB chunk


async def stream_upload_to_tempfile(
    file: UploadFile,
    *,
    max_mb: int = DEFAULT_MAX_UPLOAD_MB,
    suffix: str = "",
) -> Path:
    """UploadFile을 chunk 단위로 읽어 tempfile에 직접 stream. 메모리 2중 사용 회피.

    이전 `read_upload_limited`는 chunks 리스트에 쌓고 b"".join() → tempfile에 다시 쓰는
    구조로 큰 파일에서 메모리 2중 사용. 이 함수는 chunk를 받자마자 tempfile에 즉시 write.
    크기 한도 초과 시 즉시 중단 + tempfile 정리 + 413 예외.

    호출자 책임: try/finally로 반환된 path.unlink(missing_ok=True) 처리.
    """
    max_bytes = max_mb * 1024 * 1024
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = Path(tmp.name)
    total = 0
    try:
        while True:
            chunk = await file.read(CHUNK_SIZE_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"파일 크기가 {max_mb}MB를 초과합니다",
                )
            tmp.write(chunk)
    finally:
        tmp.close()
    return tmp_path
