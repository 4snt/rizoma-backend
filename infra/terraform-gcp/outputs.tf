output "cluster_name" {
  description = "Nome do cluster GKE"
  value       = google_container_cluster.rizoma.name
}

output "cluster_location" {
  description = "Região do cluster GKE"
  value       = google_container_cluster.rizoma.location
}

output "kubectl_command" {
  description = "Comando para configurar o kubeconfig local"
  value       = "gcloud container clusters get-credentials ${var.cluster_name} --region ${var.region} --project ${var.project_id}"
}

output "db_connection_name" {
  description = "Connection name do Cloud SQL (PROJECT:REGION:INSTANCE)"
  value       = google_sql_database_instance.postgres.connection_name
}

output "db_private_ip" {
  description = "IP privado do Cloud SQL (acessível só de dentro da VPC)"
  value       = google_sql_database_instance.postgres.private_ip_address
  sensitive   = true
}

output "db_api_user_password" {
  description = "Senha do usuário api_user no PostgreSQL"
  value       = random_password.db_api_user.result
  sensitive   = true
}

output "db_readonly_password" {
  description = "Senha do usuário readonly no PostgreSQL"
  value       = random_password.db_readonly.result
  sensitive   = true
}

output "artifact_registry_url" {
  description = "Prefixo das imagens Docker no Artifact Registry"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.ar_repository}"
}

output "workload_identity_provider" {
  description = "Provider WIF — usar em google-github-actions/auth no CI"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "github_actions_sa" {
  description = "Service Account email para o CI (google-github-actions/auth)"
  value       = google_service_account.github_actions.email
}

output "create_k8s_secret_command" {
  description = "Comando para criar o secret Kubernetes com todas as variáveis. Execute após terraform apply."
  sensitive   = true
  value       = <<-EOT
    # Execute após: gcloud container clusters get-credentials ...
    # Substitua as variáveis GOOGLE_CLIENT_ID, JWT_SECRET, AUTH_SECRET antes de rodar.

    kubectl create secret generic bio-secrets \
      --namespace=${var.namespace} \
      --from-literal=POSTGRES_HOST=$(terraform output -raw db_private_ip) \
      --from-literal=POSTGRES_PORT=5432 \
      --from-literal=POSTGRES_DB=${var.db_name} \
      --from-literal=POSTGRES_USER=api_user \
      --from-literal=POSTGRES_PASSWORD=$(terraform output -raw db_api_user_password) \
      --from-literal=ES_HOST=http://elasticsearch:9200 \
      --from-literal=GOOGLE_CLIENT_ID=PREENCHA \
      --from-literal=JWT_SECRET=PREENCHA \
      --from-literal=ALLOWED_EMAIL_DOMAIN=${var.allowed_email_domain} \
      --from-literal=JWT_ACCESS_MINUTES=60 \
      --from-literal=CORS_ORIGINS=${var.cors_origins}
  EOT
}
