resource "kubernetes_deployment" "bio_api" {
  metadata {
    name      = "bio-api"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  # Imagem ainda não importada na primeira apply — não travar esperando
  # rollout de um pod que não vai subir até a imagem existir.
  wait_for_rollout = false
  spec {
    replicas = 1
    selector {
      match_labels = { app = "bio-api" }
    }
    template {
      metadata {
        labels = { app = "bio-api" }
      }
      spec {
        container {
          name              = "bio-api"
          image             = var.api_image
          image_pull_policy = "Never" # imagem importada localmente, sem registry

          command = ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

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

          port { container_port = 8000 }

          resources {
            requests = { cpu = "200m", memory = "256Mi" }
            limits   = { cpu = "1000m", memory = "512Mi" }
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

resource "kubernetes_service" "bio_api" {
  metadata {
    name      = "bio-api"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  spec {
    selector = { app = "bio-api" }
    port {
      port        = 8000
      target_port = 8000
    }
  }
}
