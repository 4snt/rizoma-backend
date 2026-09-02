# Consumido por api e r-worker (envFrom secretRef) — nomes de chave iguais ao
# .env.example do backend para manter paridade com o ambiente Compose.
resource "kubernetes_secret" "bio_platform_secrets" {
  metadata {
    name      = "bio-platform-secrets"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }

  data = {
    POSTGRES_DB       = var.postgres_db
    POSTGRES_USER     = var.postgres_user
    POSTGRES_PASSWORD = var.postgres_password

    APP_DB_USER     = var.app_db_user
    APP_DB_PASSWORD = var.app_db_password

    SYSTEM_DB_USER     = var.system_db_user
    SYSTEM_DB_PASSWORD = var.system_db_password

    S3_ACCESS_KEY = var.s3_access_key
    S3_SECRET_KEY = var.s3_secret_key
    S3_BUCKET     = var.s3_bucket
    S3_REGION     = "us-east-1"

    S3_PUBLIC_ENDPOINT = "https://s3-rizoma.${var.domain}"

    PRESIGN_EXPIRY_SECONDS = "3600"
    MAX_UPLOAD_SIZE_MB     = "20480"

    LOG_LEVEL     = "info"
    CORS_ORIGINS  = "https://rizoma.${var.domain}"

    GOOGLE_CLIENT_ID     = var.google_client_id
    JWT_SECRET           = var.jwt_secret
    JWT_ACCESS_MINUTES   = "60"
    JWT_REFRESH_DAYS     = "7"
    WORKER_TOKEN         = var.worker_token
    ALLOWED_EMAIL_DOMAIN = var.allowed_email_domain

    JOB_HEARTBEAT_TIMEOUT_SECONDS = "300"
    JOB_MAX_ATTEMPTS              = "3"
  }
}

# Consumido só pelo bio-frontend (NextAuth) — chaves diferentes das do backend
# (auth.ts lê GOOGLE_CLIENT_ID/SECRET, AUTH_SECRET, API_URL, ALLOWED_EMAIL_DOMAIN).
resource "kubernetes_secret" "rizoma_frontend_secrets" {
  metadata {
    name      = "rizoma-frontend-secrets"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }

  data = {
    GOOGLE_CLIENT_ID     = var.google_client_id
    GOOGLE_CLIENT_SECRET = var.google_client_secret
    AUTH_SECRET           = var.auth_secret
    API_URL               = "http://bio-api:8000"
    ALLOWED_EMAIL_DOMAIN  = var.allowed_email_domain
  }
}
