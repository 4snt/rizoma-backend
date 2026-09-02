variable "project_id" {
  type        = string
  description = "ID do projeto GCP (ex: rizoma-tcc-12345)"
}

variable "region" {
  type        = string
  default     = "southamerica-east1"
  description = "Região GCP. southamerica-east1 = São Paulo — menor latência para UFVJM"
}

variable "zone" {
  type    = string
  default = "southamerica-east1-c"
}

# ── Cluster ───────────────────────────────────────────────────────────────────

variable "cluster_name" {
  type    = string
  default = "rizoma"
}

variable "namespace" {
  type    = string
  default = "bioinformatica"
  description = "Namespace Kubernetes onde rodam todos os workloads"
}

# ── Cloud SQL ─────────────────────────────────────────────────────────────────

variable "db_instance_name" {
  type    = string
  default = "rizoma-pg"
}

variable "db_name" {
  type    = string
  default = "bioinformatica"
}

variable "db_tier" {
  type    = string
  default = "db-custom-2-4096"
  description = <<-EOT
    Tier da instância Cloud SQL.
    Dev leve : db-f1-micro  (~$7/mês — sem HA, sem réplica)
    TCC prod : db-custom-2-4096  (~$65/mês — 2 vCPU, 4GB RAM, SSD)
    A análise de phyloseq via R Worker faz queries pesadas; recomendado mínimo 2 vCPU.
  EOT
}

variable "db_disk_gb" {
  type    = number
  default = 30
  description = "Tamanho inicial do disco Cloud SQL em GB. Autoscale ativado."
}

# ── Artifact Registry ─────────────────────────────────────────────────────────

variable "ar_repository" {
  type    = string
  default = "bio-platform"
  description = "Nome do repositório Docker no Artifact Registry"
}

# ── GitHub Actions (Workload Identity) ───────────────────────────────────────

variable "github_org" {
  type        = string
  description = "Organização ou usuário GitHub (ex: 4snt)"
}

variable "github_repo" {
  type        = string
  default     = "bio-platform"
  description = "Nome do repositório GitHub que terá acesso via Workload Identity"
}

# ── App ───────────────────────────────────────────────────────────────────────

variable "allowed_email_domain" {
  type    = string
  default = "@ufvjm.edu.br"
}

variable "cors_origins" {
  type        = string
  description = "URL do frontend no Vercel (ex: https://rizoma.vercel.app). Separado por vírgula se múltiplos."
}

variable "api_external_domain" {
  type        = string
  description = "Domínio público da API, sem https:// (ex: bioapi.exemplo.com). Usado no certificado gerenciado."
}
