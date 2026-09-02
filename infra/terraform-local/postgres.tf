# PostGIS, não postgres puro — o baseline do Alembic faz CREATE EXTENSION
# postgis (ADR-002/003), igual ao docker-compose.yml.
resource "kubernetes_stateful_set" "postgres" {
  metadata {
    name      = "postgres"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }

  spec {
    service_name = "postgres"
    replicas     = 1

    selector {
      match_labels = { app = "postgres" }
    }

    template {
      metadata {
        labels = { app = "postgres" }
      }

      spec {
        container {
          name  = "postgres"
          image = "postgis/postgis:16-3.4"

          env {
            name  = "POSTGRES_DB"
            value = var.postgres_db
          }
          env {
            name = "POSTGRES_USER"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.bio_platform_secrets.metadata[0].name
                key  = "POSTGRES_USER"
              }
            }
          }
          env {
            name = "POSTGRES_PASSWORD"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.bio_platform_secrets.metadata[0].name
                key  = "POSTGRES_PASSWORD"
              }
            }
          }

          port {
            container_port = 5432
          }

          volume_mount {
            name       = "pg-data"
            mount_path = "/var/lib/postgresql/data"
            sub_path   = "pgdata"
          }

          readiness_probe {
            exec {
              command = ["pg_isready", "-U", var.postgres_user, "-d", var.postgres_db]
            }
            initial_delay_seconds = 5
            period_seconds         = 5
          }
        }
      }
    }

    volume_claim_template {
      metadata {
        name = "pg-data"
      }
      spec {
        access_modes       = ["ReadWriteOnce"]
        storage_class_name = "microk8s-hostpath"
        resources {
          requests = { storage = "20Gi" }
        }
      }
    }
  }
}

resource "kubernetes_service" "postgres" {
  metadata {
    name      = "postgres"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  spec {
    selector = { app = "postgres" }
    port {
      port        = 5432
      target_port = 5432
    }
    cluster_ip = "None" # headless — casa com o StatefulSet
  }
}
