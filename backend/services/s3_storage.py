"""AWS S3 파일 저장 서비스"""

from datetime import date
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from config import settings


def _get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )


def upload_review_file(
    file_path: str | Path,
    mgmt_no: str,
    phase: str,
    original_filename: str,
) -> str:
    """검토서 파일을 S3에 업로드

    저장 경로: reviews/{년도}/{월}/{일}/{관리번호}_{단계}_{원본파일명}

    Returns:
        S3 key (파일 경로)
    """
    today = date.today()
    suffix = Path(original_filename).suffix
    s3_key = (
        f"reviews/{today.year}/{today.month:02d}/{today.day:02d}/"
        f"{mgmt_no}_{phase}{suffix}"
    )

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
