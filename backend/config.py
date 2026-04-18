"""애플리케이션 설정"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # CORS 허용 origin (JSON 배열 형식)
    cors_origins: list[str]

    # 프론트엔드 base URL (초대 링크 등 외부 발송 메시지에 사용)
    # 예: https://ksea-m.vercel.app
    frontend_base_url: str = "https://ksea-m.vercel.app"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("jwt_secret_key는 32자 이상이어야 합니다")
        return v


settings = Settings()
