# ingressClassName "public" — é o IngressClass padrão criado pelo addon
# 'ingress' do MicroK8s (Traefik interno ao cluster, exposto via Service
# LoadBalancer/NodePort). Diferente do manifest de referência do repo, que
# assumia ingress-nginx (não é o que o addon do MicroK8s instala).
resource "kubernetes_ingress_v1" "rizoma" {
  metadata {
    name      = "rizoma-ingress"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
    annotations = {
      "traefik.ingress.kubernetes.io/router.entrypoints" = "web"
    }
  }
  spec {
    ingress_class_name = "public"
    rule {
      host = "rizoma.${var.domain}"
      http {
        # NextAuth (auth.ts) é servido PELO FRONTEND em /api/auth/* — path mais
        # longo ganha do Prefix /api abaixo (backend FastAPI, tudo em /api/v2/*).
        path {
          path      = "/api/auth"
          path_type = "Prefix"
          backend {
            service {
              name = kubernetes_service.bio_frontend.metadata[0].name
              port { number = 3000 }
            }
          }
        }
        path {
          path      = "/api"
          path_type = "Prefix"
          backend {
            service {
              name = kubernetes_service.bio_api.metadata[0].name
              port { number = 8000 }
            }
          }
        }
        path {
          path      = "/"
          path_type = "Prefix"
          backend {
            service {
              name = kubernetes_service.bio_frontend.metadata[0].name
              port { number = 3000 }
            }
          }
        }
      }
    }
  }
}

# Endpoint S3 público — o frontend faz PUT/GET direto do navegador via URL
# assinada (ver comentário S3_PUBLIC_ENDPOINT no .env.example do backend); o
# navegador não resolve o nome interno 'minio', então precisa de um host
# público de verdade.
resource "kubernetes_ingress_v1" "minio" {
  metadata {
    name      = "minio-ingress"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
    annotations = {
      "traefik.ingress.kubernetes.io/router.entrypoints" = "web"
    }
  }
  spec {
    ingress_class_name = "public"
    rule {
      host = "s3-rizoma.${var.domain}"
      http {
        path {
          path      = "/"
          path_type = "Prefix"
          backend {
            service {
              name = kubernetes_service.minio.metadata[0].name
              port { number = 9000 }
            }
          }
        }
      }
    }
  }
}

resource "kubernetes_ingress_v1" "senaite" {
  metadata {
    name      = "senaite-ingress"
    namespace = kubernetes_namespace.bioinformatica.metadata[0].name
    annotations = {
      "traefik.ingress.kubernetes.io/router.entrypoints" = "web"
    }
  }
  spec {
    ingress_class_name = "public"
    rule {
      host = "senaite.${var.domain}"
      http {
        path {
          path      = "/"
          path_type = "Prefix"
          backend {
            service {
              name = kubernetes_service.senaite.metadata[0].name
              port { number = 8080 }
            }
          }
        }
      }
    }
  }
}
