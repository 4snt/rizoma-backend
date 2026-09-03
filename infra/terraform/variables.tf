variable "aws_region" {
  description = "Região AWS onde tudo é provisionado."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefixo de nomes dos recursos."
  type        = string
  default     = "rizoma"
}

variable "environment" {
  description = "Ambiente lógico (prod, staging, ...)."
  type        = string
  default     = "prod"
}

# ─────────────────────────────── Rede ───────────────────────────────
variable "vpc_cidr" {
  description = "CIDR da VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "az_count" {
  description = "Quantas AZs usar (mín. 2 para ALB e subnet group do RDS)."
  type        = number
  default     = 2
}

# ─────────────────────────────── RDS ────────────────────────────────
variable "db_instance_class" {
  description = "Classe da instância RDS. t4g.micro cabe no free-tier-ish de um TCC."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "Armazenamento inicial (GB)."
  type        = number
  default     = 20
}

variable "db_max_allocated_storage" {
  description = "Teto do autoscaling de storage (GB)."
  type        = number
  default     = 100
}

variable "db_name" {
  description = "Nome do banco. Igual ao POSTGRES_DB da aplicação."
  type        = string
  default     = "rizoma"
}

variable "db_master_username" {
  description = "Usuário dono do schema (roda as migrations). = POSTGRES_USER."
  type        = string
  default     = "api_user"
}

variable "db_master_password" {
  description = "Senha do usuário mestre do RDS. Segredo forte, obrigatório."
  type        = string
  sensitive   = true
}

variable "app_db_password" {
  description = <<-EOT
    Senha do papel de runtime NOSUPERUSER (rizoma_app), criado pela migration
    baseline a partir de APP_DB_PASSWORD. Fica só na rede interna (RDS não é
    público), mas use um valor forte em produção.
  EOT
  type      = string
  sensitive = true
  default   = "rizoma_app_pw"
}

variable "system_db_password" {
  description = "Senha do papel BYPASSRLS (rizoma_system). Ver app_db_password."
  type        = string
  sensitive   = true
  default     = "rizoma_system_pw"
}

# ───────────────────────────── Aplicação ────────────────────────────
variable "jwt_secret" {
  description = "Segredo HS256 dos JWTs da plataforma. openssl rand -hex 32."
  type        = string
  sensitive   = true
}

variable "google_client_id" {
  description = "OAuth2 Google Client ID (usado pela API e pelo frontend)."
  type        = string
  default     = ""
}

variable "google_client_secret" {
  description = "OAuth2 Google Client Secret (usado pelo NextAuth no frontend)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "auth_secret" {
  description = "AUTH_SECRET/NEXTAUTH_SECRET do NextAuth."
  type        = string
  sensitive   = true
  default     = ""
}

variable "allowed_email_domain" {
  description = "Domínio de email permitido no login."
  type        = string
  default     = "@ufvjm.edu.br"
}

# ──────────────────────── Domínios / TLS / ALB ──────────────────────
variable "app_domain" {
  description = "Host do frontend (ex: rizoma.exemplo.com). Vazio = só DNS do ALB."
  type        = string
  default     = ""
}

variable "api_domain" {
  description = "Host da API (ex: rizomaapi.exemplo.com). Vazio = só DNS do ALB."
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "ARN de um certificado ACM cobrindo app_domain e api_domain. Vazio = ALB só em HTTP:80."
  type        = string
  default     = ""
}

# ────────────────────────── Imagens (ECR) ───────────────────────────
variable "image_tag" {
  description = "Tag das imagens ECR a implantar (o CI publica :latest e :<sha>)."
  type        = string
  default     = "latest"
}

# ──────────────────────── Dimensionamento ECS ───────────────────────
variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "frontend_cpu" {
  type    = number
  default = 256
}

variable "frontend_memory" {
  type    = number
  default = 512
}

variable "frontend_desired_count" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  description = "Retenção dos log groups do CloudWatch."
  type        = number
  default     = 14
}
