variable "kubeconfig_path" {
  description = "Caminho do kubeconfig do cluster MicroK8s local"
  type        = string
  default     = "/home/snt/.kube/config-microk8s"
}

variable "namespace" {
  description = "Namespace k8s do Rizoma"
  type        = string
  default     = "bioinformatica"
}

variable "domain" {
  description = "Domínio base público"
  type        = string
  default     = "flipafile.com"
}

# ---------------------------------------------------------------------------
# Imagens — construídas localmente na VM e importadas no containerd do
# MicroK8s (sem registry externo). Ver infra/terraform-local/README.md.
# ---------------------------------------------------------------------------
variable "api_image" {
  type    = string
  default = "rizoma-api:local"
}

variable "rworker_image" {
  type    = string
  default = "rizoma-rworker:local"
}

variable "frontend_image" {
  type    = string
  default = "rizoma-frontend:local"
}

variable "senaite_image" {
  description = "Não existe tag :latest no Docker Hub oficial — usar :2.x (ou uma versão pinada)."
  type        = string
  default     = "senaite/senaite:2.x"
}

variable "senaite_admin_password" {
  description = "Senha do usuário admin do SENAITE — gerar com: openssl rand -hex 16"
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Postgres — três papéis (ver ADR-007 no rizoma-backend)
# ---------------------------------------------------------------------------
variable "postgres_db" {
  type    = string
  default = "rizoma"
}

variable "postgres_user" {
  description = "Dono do schema (roda as migrations)"
  type        = string
  default     = "api_user"
}

variable "postgres_password" {
  type      = string
  sensitive = true
}

variable "app_db_user" {
  description = "Runtime da API — NOSUPERUSER NOBYPASSRLS"
  type        = string
  default     = "rizoma_app"
}

variable "app_db_password" {
  type      = string
  sensitive = true
}

variable "system_db_user" {
  description = "Cross-organização (login, reaper, verificação pública) — BYPASSRLS"
  type        = string
  default     = "rizoma_system"
}

variable "system_db_password" {
  type      = string
  sensitive = true
}

# ---------------------------------------------------------------------------
# MinIO / S3
# ---------------------------------------------------------------------------
variable "s3_access_key" {
  type      = string
  sensitive = true
}

variable "s3_secret_key" {
  type      = string
  sensitive = true
}

variable "s3_bucket" {
  type    = string
  default = "rizoma"
}

# ---------------------------------------------------------------------------
# Auth — Google OAuth (ADR-005), sem senha
# ---------------------------------------------------------------------------
variable "enable_r_worker" {
  description = "Liga o deployment do R Worker (fora de escopo do MVP; integração mantida como débito técnico)"
  type        = bool
  default     = false
}

variable "google_client_id" {
  type      = string
  sensitive = true
}

variable "google_client_secret" {
  type      = string
  sensitive = true
}

variable "jwt_secret" {
  description = "Assinatura dos tokens da API — gerar com: openssl rand -hex 32"
  type        = string
  sensitive   = true
}

variable "auth_secret" {
  description = "AUTH_SECRET do NextAuth (frontend) — gerar com: openssl rand -hex 32"
  type        = string
  sensitive   = true
}

variable "worker_token" {
  description = "Autenticação do R Worker na API — gerar com: openssl rand -hex 32"
  type        = string
  sensitive   = true
}

variable "allowed_email_domain" {
  type    = string
  default = "@ufvjm.edu.br"
}
