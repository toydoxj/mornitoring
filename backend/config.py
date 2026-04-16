"""애플리케이션 설정"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 데이터베이스
    database_url: str = "postgresql://postgres:postgres@localhost:5432/monitoring"

    # JWT
    jwt_secret_key: str = "change-this-secret-key-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24시간

    # AWS S3
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-northeast-2"
    s3_bucket_name: str = "monitoring-reviews"

    # 카카오 API
    kakao_rest_api_key: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = "http://localhost:3000/kakao-callback"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
