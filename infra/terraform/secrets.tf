# Segredos em SSM Parameter Store (SecureString). Mais barato que o Secrets
# Manager e suficiente aqui. A execution role lê estes ARNs e o ECS injeta os
# valores como variáveis de ambiente na task (nunca aparecem em texto na task
# definition nem no console do ECS).
locals {
  secrets = {
    db_master_password = var.db_master_password
    app_db_password    = var.app_db_password
    system_db_password = var.system_db_password
    jwt_secret         = var.jwt_secret
    google_client_secret = var.google_client_secret
    auth_secret          = var.auth_secret
  }
}

resource "aws_ssm_parameter" "secret" {
  for_each = local.secrets
  name     = "/${var.project_name}/${var.environment}/${each.key}"
  type     = "SecureString"
  value    = each.value
}
