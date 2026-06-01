"""애플리케이션 설정"""

import json
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def get_sqlalchemy_database_url(database_url: str) -> str:
    """SQLAlchemy/Alembic에서 사용할 DB URL을 반환한다."""
    parsed = urlsplit(database_url)
    host = parsed.hostname or ""
    if host.endswith(".pooler.supabase.com") and parsed.port == 5432:
        # Supabase pooler 5432는 session mode라 Render 인스턴스 풀이 한도를 쉽게 채운다.
        # transaction mode(6543)를 사용하면 pre-deploy와 런타임 커넥션 고갈을 완화할 수 있다.
        netloc = parsed.netloc
        if netloc.endswith(":5432"):
            netloc = f"{netloc[:-5]}:6543"
            return urlunsplit(parsed._replace(netloc=netloc))
    return database_url


class Settings(BaseSettings):
    # 데이터베이스 (필수)
    database_url: str

    # JWT (secret은 32자 이상 필수)
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24시간

    # AWS S3
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str
    s3_bucket_name: str

    # 카카오 API
    kakao_rest_api_key: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str

    # CORS 허용 origin.
    # 환경변수는 콤마 구분 문자열(https://a.com,https://b.com) 또는
    # JSON 배열(["https://a.com"]) 둘 다 허용한다. NoDecode로 자동 JSON 디코딩을 끄고
    # 아래 validator에서 직접 파싱한다(콤마 구분값이 JSON 파싱 에러를 내는 문제 방지).
    cors_origins: Annotated[list[str], NoDecode]

    # 프론트엔드 base URL (초대 링크 등 외부 발송 메시지에 사용)
    # 예: https://moni.ksea.or.kr
    frontend_base_url: str = "https://moni.ksea.or.kr"

    # 신뢰하는 프록시 hop 수.
    # 0 = X-Forwarded-For/X-Real-IP를 신뢰하지 않음(스푸핑 방지). request.client.host만 사용.
    # 1 = 가장 마지막 hop이 trusted proxy(예: Render/Vercel LB) → XFF 우측에서 1개 안쪽이 원 클라.
    # 운영(Render)에서 1로 설정하면 LB 헤더만 신뢰한다.
    trusted_proxy_hops: int = 0

    # 관리자 통계 API 짧은 캐시 TTL(초). 0이면 비활성화.
    # 여러 관리자가 같은 대시보드를 동시에 열 때 반복 집계 쿼리를 줄인다.
    stats_cache_ttl_seconds: int = 5

    # SQLAlchemy DB 커넥션 풀. Supabase pooler 한도가 낮으므로 프로세스당
    # 커넥션 수를 작게 유지하고, 대기는 짧게 끝낸다.
    db_pool_size: int = 2
    db_max_overflow: int = 1
    db_pool_timeout_seconds: int = 3

    @property
    def sqlalchemy_database_url(self) -> str:
        return get_sqlalchemy_database_url(self.database_url)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: object) -> list[str]:
        # 이미 리스트면 그대로 사용(코드에서 직접 주입한 경우)
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            # JSON 배열 형식이면 JSON으로 파싱
            if s.startswith("["):
                return json.loads(s)
            # 그 외에는 콤마 구분 문자열로 파싱(공백/빈 항목 제거)
            return [item.strip() for item in s.split(",") if item.strip()]
        raise ValueError("cors_origins는 콤마 구분 문자열 또는 JSON 배열이어야 합니다")

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("jwt_secret_key는 32자 이상이어야 합니다")
        return v


settings = Settings()
