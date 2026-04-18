"""공용 FastAPI 의존성/헬퍼."""

from fastapi import HTTPException, UploadFile

# 업로드 크기 제한 (MB)
DEFAULT_MAX_UPLOAD_MB = 10        # 일반 파일 (엑셀/검토서 등)
ATTACHMENT_MAX_UPLOAD_MB = 20     # 공지/토론 첨부 (이미지 포함 가능성)
CHUNK_SIZE_BYTES = 1024 * 1024     # 1MB chunk


async def read_upload_limited(
    file: UploadFile, *, max_mb: int = DEFAULT_MAX_UPLOAD_MB
) -> bytes:
    """UploadFile을 chunk 단위로 읽으며 크기 한도 검사. 초과 시 413.

    `await file.read()`는 전체를 한 번에 메모리로 올려 큰 파일이 OOM/DoS 위험.
    이 헬퍼는 1MB chunk로 누적하면서 한도 검사 → 초과 즉시 중단·예외.
    """
    max_bytes = max_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK_SIZE_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기가 {max_mb}MB를 초과합니다",
            )
        chunks.append(chunk)
    return b"".join(chunks)
