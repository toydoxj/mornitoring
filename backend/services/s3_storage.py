"""AWS S3 파일 저장 서비스"""

from datetime import date
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from config import settings


@lru_cache(maxsize=1)
def _get_s3_client():
    """워커당 1회만 boto3 클라이언트 생성 (각 호출당 ~50ms 절약).

    boto3 client 생성은 무겁고, settings는 프로세스 lifetime 동안 변경되지 않으므로
    프로세스(워커) 단위 캐싱이 안전하다.
    """
    return boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )


PHASE_FOLDER_MAP = {
    "preliminary": "예비검토",
    "supplement_1": "보완검토(1차)",
    "supplement_2": "보완검토(2차)",
    "supplement_3": "보완검토(3차)",
    "supplement_4": "보완검토(4차)",
    "supplement_5": "보완검토(5차)",
}


def upload_review_file(
    file_path: str | Path,
    mgmt_no: str,
    phase: str,
    original_filename: str,
) -> str:
    """검토서 파일을 S3에 업로드

    저장 경로: reviews/{예비검토|보완검토(N차)}/{YYYY-MM-DD}/{관리번호}.xlsm

    Returns:
        S3 key (파일 경로)
    """
    today = date.today()
    suffix = Path(original_filename).suffix
    phase_folder = PHASE_FOLDER_MAP.get(phase, phase)
    date_folder = today.strftime("%Y-%m-%d")
    s3_key = f"reviews/{phase_folder}/{date_folder}/{mgmt_no}{suffix}"

    if not settings.aws_access_key_id:
        # S3 미설정 시 로컬 모드 (key만 반환)
        return s3_key

    client = _get_s3_client()
    client.upload_file(
        str(file_path),
        settings.s3_bucket_name,
        s3_key,
        ExtraArgs={"ContentType": "application/vnd.ms-excel.sheet.macroEnabled.12"},
    )
    return s3_key


def get_download_url(s3_key: str, expires_in: int = 3600) -> str:
    """S3 presigned URL 생성 (다운로드용)

    Args:
        s3_key: S3 파일 경로
        expires_in: URL 유효 시간 (초, 기본 1시간)

    Returns:
        presigned URL
    """
    if not settings.aws_access_key_id:
        return ""

    client = _get_s3_client()
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": s3_key},
            ExpiresIn=expires_in,
        )
        return url
    except ClientError:
        return ""


def list_review_files(prefix: str = "reviews/") -> list[dict]:
    """S3에 저장된 검토서 파일 목록 조회"""
    if not settings.aws_access_key_id:
        return []

    client = _get_s3_client()
    try:
        paginator = client.get_paginator("list_objects_v2")
        files = []
        for page in paginator.paginate(Bucket=settings.s3_bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                parts = key.split("/")
                # 새 형식: reviews/{phase_folder}/{date}/{filename}
                # 구 형식: reviews/{year}/{month}/{day}/{filename}
                if len(parts) >= 4:
                    filename = parts[-1]
                    if not filename:
                        continue
                    # 구 형식 감지 (parts[1]이 숫자면 구 형식)
                    if parts[1].isdigit():
                        phase = "기존"
                        date_str = f"{parts[1]}-{parts[2]}-{parts[3]}"
                        if len(parts) >= 5:
                            filename = parts[4]
                        else:
                            continue
                    else:
                        phase = parts[1]
                        date_str = parts[2]

                    files.append({
                        "key": key,
                        "phase": phase,
                        "date": date_str,
                        "filename": filename,
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                    })
        return files
    except ClientError:
        return []


def delete_file(s3_key: str) -> bool:
    """S3 파일 삭제"""
    if not settings.aws_access_key_id:
        return True

    client = _get_s3_client()
    try:
        client.delete_object(Bucket=settings.s3_bucket_name, Key=s3_key)
        return True
    except ClientError:
        return False


def upload_generic_file(
    file_path: str | Path,
    s3_key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """임의 경로에 파일 업로드 (S3 미설정 시 키만 반환)"""
    if not settings.aws_access_key_id:
        return s3_key

    client = _get_s3_client()
    client.upload_file(
        str(file_path),
        settings.s3_bucket_name,
        s3_key,
        ExtraArgs={"ContentType": content_type},
    )
    return s3_key
