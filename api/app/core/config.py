from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "bioinformatica"
    postgres_user: str = "api_user"
    postgres_password: str = "changeme"

    es_host: str = "http://localhost:9200"

    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"   # usado nas presigned URLs (acessível pelo browser)
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "changeme"
    minio_secure: bool = False

    log_level: str = "info"

    google_client_id: str = ""
    jwt_secret: str = "change-me-in-production"
    jwt_access_minutes: int = 60
    jwt_refresh_days: int = 7
    allowed_email_domain: str = "@ufvjm.edu.br"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_raw(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"


settings = Settings()
