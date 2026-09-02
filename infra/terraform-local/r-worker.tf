# Sem nodeSelector/toleration de nó nomeado (agent-1) do manifest de
# referência — aqui é nó único. Sem Service: o worker não recebe requisição,
# só consome a fila via Postgres LISTEN/NOTIFY.
resource "kubernetes_deployment" "bio_r_worker" {
  metadata {
    name      = "bio-r-worker"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  wait_for_rollout = false
  spec {
    replicas = 1
    selector {
      match_labels = { app = "bio-r-worker" }
    }
    template {
      metadata {
        labels = { app = "bio-r-worker" }
      }
      spec {
        container {
          name              = "bio-r-worker"
          image             = var.rworker_image
          image_pull_policy = "Never"

          env_from {
            secret_ref {
              name = kubernetes_secret.bio_platform_secrets.metadata[0].name
            }
          }
          env {
            name  = "POSTGRES_HOST"
            value = "postgres"
          }
          env {
            name  = "POSTGRES_PORT"
            value = "5432"
          }
          env {
            name  = "S3_ENDPOINT"
            value = "http://minio:9000"
          }

          resources {
            requests = { cpu = "500m", memory = "1Gi" }
            limits   = { cpu = "2000m", memory = "4Gi" }
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_stateful_set.postgres,
    kubernetes_job.minio_init,
  ]
}
