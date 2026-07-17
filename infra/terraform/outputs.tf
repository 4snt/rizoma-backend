output "alb_dns_name" {
  description = "DNS público do ALB. Aponte seus domínios (CNAME) para cá."
  value       = aws_lb.main.dns_name
}

output "public_base_url" {
  description = "URL pública da aplicação (frontend + API no mesmo host)."
  value       = local.public_base
}

output "rds_endpoint" {
  description = "Endpoint do Postgres (host:porta)."
  value       = aws_db_instance.main.endpoint
}

output "s3_bucket" {
  description = "Nome do bucket de object storage."
  value       = aws_s3_bucket.storage.bucket
}

output "ecr_repositories" {
  description = "URLs dos repositórios ECR (para o CI dar push)."
  value       = { for k, r in aws_ecr_repository.repo : k => r.repository_url }
}

output "ecs_cluster" {
  description = "Nome do cluster ECS (para o CI dar force-new-deployment)."
  value       = aws_ecs_cluster.main.name
}

output "build_time_frontend_env" {
  description = "Valores para o CI buildar a imagem do frontend (NEXT_PUBLIC_* são baked em build-time)."
  value = {
    NEXT_PUBLIC_API_URL = local.public_base
    NEXT_PUBLIC_WS_URL  = local.ws_base
  }
}
