# Sem manifest de referência (infra/manifests/ só tinha api + r-worker +
# postgres) — criado com base no Dockerfile e no auth.ts do repo 'rizoma'.
resource "kubernetes_deployment" "bio_frontend" {
  metadata {
    name      = "bio-frontend"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  wait_for_rollout = false
  spec {
    replicas = 1
    selector {
      match_labels = { app = "bio-frontend" }
    }
    template {
      metadata {
        labels = { app = "bio-frontend" }
      }
      spec {
        container {
          name              = "bio-frontend"
          image             = var.frontend_image
          image_pull_policy = "Never"

          env_from {
            secret_ref {
              name = kubernetes_secret.rizoma_frontend_secrets.metadata[0].name
            }
          }
          env {
            name  = "AUTH_URL"
            value = "https://rizoma.${var.domain}"
          }
          env {
            name  = "NEXTAUTH_URL"
            value = "https://rizoma.${var.domain}"
          }

          port { container_port = 3000 }

          resources {
            requests = { cpu = "200m", memory = "256Mi" }
            limits   = { cpu = "500m", memory = "512Mi" }
          }
        }
      }
    }
  }

  depends_on = [kubernetes_deployment.bio_api]
}

resource "kubernetes_service" "bio_frontend" {
  metadata {
    name      = "bio-frontend"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  spec {
    selector = { app = "bio-frontend" }
    port {
      port        = 3000
      target_port = 3000
    }
  }
}
