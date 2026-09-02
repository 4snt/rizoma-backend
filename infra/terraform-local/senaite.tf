# SENAITE — concorrente para comparação com o Rizoma na defesa do TCC
# (é o topo da tabela comparativa de tcc/AnalisePadroesLIMS.tex: LIMS open
# source genérico, sucessor do Bika LIMS). Independente do Rizoma de
# propósito — usa o storage padrão dele (ZODB/blobstorage em PVC), sem
# integrar com o Postgres do Rizoma.
#
# NOTA: variáveis de ambiente/porta conferidas contra a doc oficial da
# imagem senaite/senaite na primeira aplicação — ajustar se o upstream tiver
# mudado.
resource "kubernetes_persistent_volume_claim" "senaite_data" {
  metadata {
    name      = "senaite-data"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  wait_until_bound = false
  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = "microk8s-hostpath"
    resources {
      requests = { storage = "20Gi" }
    }
  }
}

resource "kubernetes_secret" "senaite_secrets" {
  metadata {
    name      = "senaite-secrets"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  data = {
    ADMIN_USER     = "admin"
    ADMIN_PASSWORD = var.senaite_admin_password
  }
}

resource "kubernetes_deployment" "senaite" {
  metadata {
    name      = "senaite"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  wait_for_rollout = false # imagem pesada (~500MB), primeiro pull demora
  spec {
    replicas = 1
    selector {
      match_labels = { app = "senaite" }
    }
    template {
      metadata {
        labels = { app = "senaite" }
      }
      spec {
        container {
          name  = "senaite"
          image = var.senaite_image

          env_from {
            secret_ref {
              name = kubernetes_secret.senaite_secrets.metadata[0].name
            }
          }
          env {
            name  = "SITE"
            value = "senaite"
          }

          port { container_port = 8080 }

          volume_mount {
            name       = "data"
            mount_path = "/data"
          }

          resources {
            requests = { cpu = "250m", memory = "512Mi" }
            limits   = { cpu = "1000m", memory = "1536Mi" }
          }
        }

        volume {
          name = "data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.senaite_data.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "senaite" {
  metadata {
    name      = "senaite"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
  }
  spec {
    selector = { app = "senaite" }
    port {
      port        = 8080
      target_port = 8080
    }
  }
}
