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

    # SQLAlchemy DB 커넥션 풀. 대시보드가 여러 API를 병렬 호출하므로
    # 기본값은 소규모 운영 동시 접속을 버틸 정도로 두고, Supabase/Render 한도에
    # 맞춰 환경변수(DB_POOL_SIZE 등)로 더 낮추거나 높일 수 있게 한다.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 10

    # --- 통계 분석 챗봇 (OpenAI) ---
    # 키가 비어 있으면 챗봇 API가 503을 돌려주고 프론트는 버튼을 숨긴다.
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-luna"
    # 추론 강도. low로 시작하고 답변 품질을 보며 조정한다.
    openai_reasoning_effort: str = "low"
    # 답변 길이 상한(토큰). 도구 호출 루프와 별개로 최종 답변에만 적용.
    stats_chat_max_output_tokens: int = 1200
    # LLM이 생성한 SELECT의 한 번 조회 최대 행수 (강제로 LIMIT 주입)
    stats_chat_row_limit: int = 200
    # SELECT 1건당 DB statement_timeout (밀리초)
    stats_chat_sql_timeout_ms: int = 5000
    # 질문 1건당 허용하는 SQL 실행 횟수 상한 (무한 루프 방지)
    stats_chat_max_sql_calls: int = 6
    # 사용자별 분당 질문 수 상한
    stats_chat_rate_limit_per_minute: int = 10

    # --- 검토의견 조합 라벨 LLM 보완 (scripts/label_opinions.py) ---
    # 규칙 사전으로 분류되지 않은 의견만 LLM에 보낸다. 비용이 무한정 늘지 않도록
    # 한 번 실행에서 처리할 의견 수와 재시도 횟수에 상한을 둔다.
    opinion_label_batch_size: int = 20          # LLM 1회 호출에 묶는 의견 수
    opinion_label_max_runs_per_execution: int = 1000  # 스크립트 1회 실행 처리 상한
    opinion_label_max_attempts: int = 3         # 같은 건 재시도 상한
    opinion_label_max_output_tokens: int = 4000
    opinion_label_max_content_chars: int = 1200  # 의견 1건당 전송 길이 상한

    # 배포된 커밋 SHA. Render가 배포 시 RENDER_GIT_COMMIT으로 자동 주입한다.
    # 헬스체크로 노출해 "지금 운영에 어떤 코드가 떠 있는지"를 밖에서 확인할 수 있게 한다.
    # 로컬 실행 시에는 비어 있다.
    render_git_commit: str = ""

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
