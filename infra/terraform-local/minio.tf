# Object storage (ADR-001) — sem manifest de referência no repo, espelhando o
# serviço 'minio' do docker-compose.yml.
resource "kubernetes_persistent_volume_claim" "minio_data" {
  metadata {
    name      = "minio-data"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  # A storage class é WaitForFirstConsumer — só vincula quando um pod é
  # agendado nela. Esperar o bind aqui travaria o apply (o pod que dispara o
  # bind é criado só depois, no Deployment).
  wait_until_bound = false
  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = "microk8s-hostpath"
    resources {
      requests = { storage = "50Gi" }
    }
  }
}

resource "kubernetes_deployment" "minio" {
  metadata {
    name      = "minio"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  spec {
    replicas = 1
    selector {
      match_labels = { app = "minio" }
    }
    template {
      metadata {
        labels = { app = "minio" }
      }
      spec {
        container {
          name  = "minio"
          image = "minio/minio"
          args  = ["server", "/data", "--console-address", ":9001"]

          env {
            name = "MINIO_ROOT_USER"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.bio_platform_secrets.metadata[0].name
                key  = "S3_ACCESS_KEY"
              }
            }
          }
          env {
            name = "MINIO_ROOT_PASSWORD"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.bio_platform_secrets.metadata[0].name
                key  = "S3_SECRET_KEY"
              }
            }
          }

          port { container_port = 9000 }
          port { container_port = 9001 }

          volume_mount {
            name       = "data"
            mount_path = "/data"
          }

          readiness_probe {
            http_get {
              path = "/minio/health/live"
              port = 9000
            }
            initial_delay_seconds = 5
            period_seconds         = 5
          }
        }

        volume {
          name = "data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.minio_data.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "minio" {
  metadata {
    name      = "minio"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  spec {
    selector = { app = "minio" }
    port {
      name        = "api"
      port        = 9000
      target_port = 9000
    }
    port {
      name        = "console"
      port        = 9001
      target_port = 9001
    }
  }
}

# Job de uma tacada só, equivalente ao 'minio-init' do docker-compose: cria o
# bucket e sai. Sem ele, o primeiro PUT assinado devolve NoSuchBucket.
resource "kubernetes_job" "minio_init" {
  metadata {
    name      = "minio-init"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  spec {
    template {
      metadata {
        labels = { app = "minio-init" }
      }
      spec {
        restart_policy = "OnFailure"
        container {
          name  = "minio-init"
          image = "minio/mc"
          env {
            name = "S3_ACCESS_KEY"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.bio_platform_secrets.metadata[0].name
                key  = "S3_ACCESS_KEY"
              }
            }
          }
          env {
            name = "S3_SECRET_KEY"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.bio_platform_secrets.metadata[0].name
                key  = "S3_SECRET_KEY"
              }
            }
          }
          env {
            name = "S3_BUCKET"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.bio_platform_secrets.metadata[0].name
                key  = "S3_BUCKET"
              }
            }
          }
          command = ["sh", "-c", <<-EOT
            mc alias set local http://minio:9000 "$S3_ACCESS_KEY" "$S3_SECRET_KEY" &&
            mc mb --ignore-existing "local/$S3_BUCKET" &&
            mc anonymous set none "local/$S3_BUCKET"
          EOT
          ]
        }
      }
    }
    backoff_limit = 6
  }

  depends_on = [kubernetes_service.minio]
}
