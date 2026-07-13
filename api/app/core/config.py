from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rizoma"

    # Dono do schema. Roda as migrations. Em dev é superusuário.
    postgres_user: str = "api_user"
    postgres_password: str = "changeme"

    # Papel de RUNTIME da API. Precisa ser NOSUPERUSER: no Postgres, superusuário
    # ignora Row-Level Security silenciosamente, o que tornaria a policy decorativa
    # e o isolamento entre organizações, ficção. (ADR-007)
    app_db_user: str = "rizoma_app"
    app_db_password: str = "rizoma_app_pw"

    # Papel com BYPASSRLS para trabalho legitimamente cross-org: login (ler
    # invitations antes de haver org), reaper de jobs, verificação pública de
    # laudo. Nunca usado num handler de requisição de usuário comum.
    system_db_user: str = "rizoma_system"
    system_db_password: str = "rizoma_system_pw"

    # Token compartilhado que o R Worker apresenta nos endpoints /worker/*.
    worker_token: str = "dev-worker-token"

    # Object storage — ADR-001: substitui PostgreSQL Large Objects.
    # s3_public_endpoint é o host que o browser enxerga; dentro da rede de
    # containers o endpoint interno é outro, e a URL assinada precisa do público.
    s3_endpoint: str = "http://localhost:9000"
    s3_public_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "rizoma"
    s3_secret_key: str = "rizoma123"
    s3_bucket: str = "rizoma"
    s3_region: str = "us-east-1"
    presign_expiry_seconds: int = 3600

    max_upload_size_mb: int = 20480

    log_level: str = "info"

    google_client_id: str = ""
    jwt_secret: str = "change-me-in-production"
    jwt_access_minutes: int = 60
    jwt_refresh_days: int = 7
    allowed_email_domain: str = "@ufvjm.edu.br"

    cors_origins: str = "http://localhost:3000"

    # Reaper: job cujo worker não bate heartbeat há N segundos volta para a fila.
    job_heartbeat_timeout_seconds: int = 300
    job_max_attempts: int = 3

    @property
    def postgres_dsn(self) -> str:
        """DSN de runtime — papel sem superusuário, RLS aplicada."""
        return (
            f"postgresql+asyncpg://{self.app_db_user}:{self.app_db_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def migration_dsn(self) -> str:
        """DSN de migration — dono do schema, driver SÍNCRONO.

        psycopg, e não asyncpg: asyncpg roda tudo como prepared statement, que
        recusa múltiplos comandos num mesmo execute. Migration é DDL em bloco.
        """
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
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
        extra = "ignore"


settings = Settings()
