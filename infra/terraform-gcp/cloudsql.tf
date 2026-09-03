# ── Passwords geradas pelo Terraform ─────────────────────────────────────────
# Ficam no state file (sensível). Use `terraform output -json` para consultar.

resource "random_password" "db_api_user" {
  length  = 32
  special = false   # RPostgres / asyncpg aceitam qualquer char, mas simplicidade first
}

resource "random_password" "db_readonly" {
  length  = 32
  special = false
}

# ── Instância PostgreSQL 16 ───────────────────────────────────────────────────

resource "google_sql_database_instance" "postgres" {
  name             = var.db_instance_name
  database_version = "POSTGRES_16"
  region           = var.region

  # Depende do peering para que o IP privado seja alocável
  depends_on = [google_service_networking_connection.sql_vpc]

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"    # "REGIONAL" para HA (failover automático, ~2× custo)
    disk_autoresize   = true
    disk_autoresize_limit = 100    # teto em GB
    disk_size         = var.db_disk_gb
    disk_type         = "PD_SSD"

    ip_configuration {
      ipv4_enabled    = false                        # sem IP público
      private_network = google_compute_network.vpc.id
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "03:00"       # UTC = meia-noite em Brasília

      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    database_flags {
      name  = "max_connections"
      value = "200"
    }

    # LISTEN/NOTIFY não precisa de flags adicionais no PostgreSQL 16
  }

  deletion_protection = false  # mude para true antes de ir pra produção real
}

# ── Banco de dados ────────────────────────────────────────────────────────────

resource "google_sql_database" "bioinformatica" {
  name     = var.db_name
  instance = google_sql_database_instance.postgres.name
}

# ── Usuários ──────────────────────────────────────────────────────────────────
# As permissões internas (GRANT) são aplicadas pelas migrations da API no startup.

resource "google_sql_user" "api_user" {
  name     = "api_user"
  instance = google_sql_database_instance.postgres.name
  password = random_password.db_api_user.result
}

resource "google_sql_user" "readonly" {
  name     = "readonly"
  instance = google_sql_database_instance.postgres.name
  password = random_password.db_readonly.result
}
