"""PostgreSQL 논리 백업 스크립트 (운영 DB → S3 오프사이트 덤프).

- `pg_dump -Fc` 커스텀 포맷으로 덤프 파일 생성
- 업로드 전 `pg_restore --list` 카탈로그 파싱 + 최소 크기 검증
  (sha256 은 전송 무결성만 보장하므로 "성공했지만 복구 불가능한 덤프"를 차단)
- SHA-256 체크섬 + 메타 JSON + 완료 마커(`.complete`) 동반 업로드
  → 복구 도구는 `.complete` 가 있는 세트만 유효한 백업으로 취급한다.
- `DATABASE_URL` 은 `PG*` 환경 변수로 분해해 전달 (프로세스 인자 노출 방지)
- S3 서버사이드 암호화(기본 AES256, BACKUP_KMS_KEY_ID 지정 시 aws:kms)

## 필수 환경 변수
- DATABASE_URL          : 백업 대상 PostgreSQL 접속 URL
- BACKUP_S3_BUCKET      : 덤프를 저장할 S3 버킷 (별도 계정/리전 권장)
- AWS_REGION            : 백업 버킷 리전
- AWS_ACCESS_KEY_ID     : 백업 전용 IAM 키 (PutObject 최소 권한)
- AWS_SECRET_ACCESS_KEY

## 선택 환경 변수
- BACKUP_S3_PREFIX      : S3 key prefix (기본 "db/")
- BACKUP_KMS_KEY_ID     : 지정 시 SSE-KMS
- BACKUP_LABEL          : 파일명에 붙일 라벨 (예: "manual", "pre-migration")
- BACKUP_MIN_DUMP_BYTES : 덤프 최소 크기 가드 (기본 100000 — 미만이면 무효 백업으로 중단)

로컬 수동 실행은 자격증명 노출 위험이 있으므로 권장하지 않으며,
원칙적으로 GitHub Actions / Render Cron 에서만 실행한다.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse


import boto3
from botocore.exceptions import BotoCoreError, ClientError


_REQUIRED_ENV = (
    "DATABASE_URL",
    "BACKUP_S3_BUCKET",
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)


def _require_env() -> dict[str, str]:
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        print(f"[backup_db] 필수 환경 변수 누락: {missing}", file=sys.stderr)
        sys.exit(2)
    return {k: os.environ[k] for k in _REQUIRED_ENV}


def _pg_env_from_url(database_url: str) -> dict[str, str]:
    """DATABASE_URL 을 PG* 환경 변수로 분해.

    argv 에 비밀번호·호스트가 드러나지 않도록 libpq 규약을 사용한다.
    """
    parsed = urllib.parse.urlparse(database_url)
    if parsed.scheme not in ("postgres", "postgresql"):
        print(f"[backup_db] 지원하지 않는 스킴: {parsed.scheme}", file=sys.stderr)
        sys.exit(2)

    env = os.environ.copy()
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    env["PGPORT"] = str(parsed.port or 5432)
    if parsed.username:
        env["PGUSER"] = urllib.parse.unquote(parsed.username)
    if parsed.password:
        env["PGPASSWORD"] = urllib.parse.unquote(parsed.password)
    database = parsed.path.lstrip("/")
    if not database:
        # libpq 는 dbname 누락 시 사용자명과 같은 DB 로 폴백한다.
        # 의도하지 않은 DB 를 조용히 덤프하는 사고를 막기 위해 즉시 실패.
        print("[backup_db] DATABASE_URL 에 데이터베이스명이 없음", file=sys.stderr)
        sys.exit(2)
    env["PGDATABASE"] = database

    qs = urllib.parse.parse_qs(parsed.query)
    # Supabase 는 SSL 필수. 명시되지 않은 경우 require 로 강제.
    env["PGSSLMODE"] = qs.get("sslmode", ["require"])[0]
    # 연결 단계 무한 대기 방지 (네트워크 스톨 시 30분 job timeout 까지 잡아먹지 않도록)
    env.setdefault("PGCONNECT_TIMEOUT", "30")
    return env


def _run_pg_dump(pg_env: dict[str, str], output_path: pathlib.Path) -> None:
    """pg_dump 실행. argv 에 자격증명을 실지 않는다."""
    cmd = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, env=pg_env)
    except FileNotFoundError:
        print("[backup_db] pg_dump 바이너리를 찾을 수 없음", file=sys.stderr)
        sys.exit(3)
    except subprocess.CalledProcessError as exc:
        print(f"[backup_db] pg_dump 실패 (exit={exc.returncode})", file=sys.stderr)
        sys.exit(exc.returncode or 1)


def _sanitize_label(raw: str) -> str:
    """라벨을 파일명·S3 키 안전 문자로 정규화.

    공백·슬래시 등이 들어오면 임시 파일 경로가 깨지거나 S3 키 계층이 오염되므로
    영숫자 · `.` `_` `-` 외에는 하이픈으로 치환하고 40자로 제한한다.
    """
    return re.sub(r"[^A-Za-z0-9._-]+", "-", raw.strip()).strip("-")[:40]


def _verify_dump(dump_path: pathlib.Path, size_bytes: int) -> int:
    """덤프 유효성 검증 후 카탈로그 항목 수 반환.

    sha256 은 전송 무결성만 보장하므로, 빈 DB 덤프나 손상된 파일이
    `.complete` 마커를 받는 "조용한 무효 백업"을 여기서 차단한다.
    """
    min_bytes = int(os.environ.get("BACKUP_MIN_DUMP_BYTES", "100000"))
    if size_bytes < min_bytes:
        print(
            f"[backup_db] 덤프 크기 {size_bytes:,}B < 최소 {min_bytes:,}B"
            " — 무효 백업으로 중단",
            file=sys.stderr,
        )
        sys.exit(5)
    try:
        out = subprocess.check_output(
            ["pg_restore", "--list", str(dump_path)], text=True
        )
    except FileNotFoundError:
        print("[backup_db] pg_restore 바이너리를 찾을 수 없음", file=sys.stderr)
        sys.exit(5)
    except subprocess.CalledProcessError as exc:
        print(
            f"[backup_db] pg_restore --list 검증 실패 (exit={exc.returncode})",
            file=sys.stderr,
        )
        sys.exit(5)
    entries = [ln for ln in out.splitlines() if ln and not ln.startswith(";")]
    if not entries:
        print("[backup_db] 덤프 카탈로그가 비어 있음 — 무효 백업으로 중단", file=sys.stderr)
        sys.exit(5)
    return len(entries)


def _sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _alembic_head(pg_env: dict[str, str]) -> str | None:
    """alembic_version.version_num 을 조회해 덤프와 함께 기록."""
    try:
        import psycopg2
    except ImportError:
        print("[backup_db] psycopg2 없음 — alembic head 기록 생략", file=sys.stderr)
        return None
    dsn = {
        "host": pg_env.get("PGHOST"),
        "port": pg_env.get("PGPORT"),
        "user": pg_env.get("PGUSER"),
        "password": pg_env.get("PGPASSWORD"),
        "dbname": pg_env.get("PGDATABASE"),
        "sslmode": pg_env.get("PGSSLMODE", "require"),
    }
    dsn = {k: v for k, v in dsn.items() if v}
    try:
        with psycopg2.connect(**dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
                row = cur.fetchone()
                return row[0] if row else None
    except psycopg2.Error as exc:
        print(f"[backup_db] alembic head 조회 실패: {exc}", file=sys.stderr)
        return None


def _pg_dump_version() -> str:
    try:
        out = subprocess.check_output(["pg_dump", "--version"], text=True)
        return out.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"


def _extra_args(kms_key: str | None) -> dict[str, str]:
    if kms_key:
        return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key}
    return {"ServerSideEncryption": "AES256"}


def main() -> int:
    env = _require_env()
    prefix = os.environ.get("BACKUP_S3_PREFIX", "db/").rstrip("/") + "/"
    kms_key = os.environ.get("BACKUP_KMS_KEY_ID") or None
    label = _sanitize_label(os.environ.get("BACKUP_LABEL", ""))
    pg_env = _pg_env_from_url(env["DATABASE_URL"])

    now = _dt.datetime.now(_dt.timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    base = f"{ts}-{label}" if label else ts
    key_dump = f"{prefix}{now:%Y/%m}/{base}.dump"
    key_sha = f"{key_dump}.sha256"
    key_meta = f"{key_dump}.meta.json"
    key_complete = f"{key_dump}.complete"

    s3 = boto3.client(
        "s3",
        region_name=env["AWS_REGION"],
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
    )
    extra = _extra_args(kms_key)

    with tempfile.TemporaryDirectory() as tmp:
        dump_path = pathlib.Path(tmp) / f"{base}.dump"
        print(f"[backup_db] pg_dump 시작 → {dump_path}")
        started_at = _dt.datetime.now(_dt.timezone.utc)
        _run_pg_dump(pg_env, dump_path)
        finished_at = _dt.datetime.now(_dt.timezone.utc)

        size_bytes = dump_path.stat().st_size
        catalog_entries = _verify_dump(dump_path, size_bytes)
        checksum = _sha256_of(dump_path)
        meta = {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": (finished_at - started_at).total_seconds(),
            "size_bytes": size_bytes,
            "catalog_entries": catalog_entries,
            "sha256": checksum,
            "pg_dump_version": _pg_dump_version(),
            "alembic_head": _alembic_head(pg_env),
            "label": label or None,
            "s3_bucket": env["BACKUP_S3_BUCKET"],
            "s3_key": key_dump,
        }

        print(
            f"[backup_db] 덤프 완료 size={size_bytes:,}B "
            f"entries={catalog_entries} "
            f"sha256={checksum[:12]}… alembic={meta['alembic_head']}"
        )

        try:
            # 업로드 순서: dump → sha → meta → complete 마커.
            # 마지막 마커가 없으면 "부분 업로드" 로 간주해 복구 대상에서 제외한다.
            s3.upload_file(
                str(dump_path),
                env["BACKUP_S3_BUCKET"],
                key_dump,
                ExtraArgs=extra,
            )
            s3.put_object(
                Bucket=env["BACKUP_S3_BUCKET"],
                Key=key_sha,
                Body=f"{checksum}  {base}.dump\n".encode(),
                ContentType="text/plain",
                **extra,
            )
            s3.put_object(
                Bucket=env["BACKUP_S3_BUCKET"],
                Key=key_meta,
                Body=json.dumps(meta, ensure_ascii=False, indent=2).encode(),
                ContentType="application/json",
                **extra,
            )
            s3.put_object(
                Bucket=env["BACKUP_S3_BUCKET"],
                Key=key_complete,
                Body=json.dumps(
                    {
                        "completed_at": _dt.datetime.now(
                            _dt.timezone.utc
                        ).isoformat(),
                        "dump": key_dump,
                        "sha256": checksum,
                    },
                    ensure_ascii=False,
                ).encode(),
                ContentType="application/json",
                **extra,
            )
        except (BotoCoreError, ClientError) as exc:
            print(f"[backup_db] S3 업로드 실패: {exc}", file=sys.stderr)
            return 4

    print(f"[backup_db] 완료 s3://{env['BACKUP_S3_BUCKET']}/{key_dump}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
