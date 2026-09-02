resource "kubernetes_namespace" "bioinformatica" {
  metadata {
    name = var.namespace
  }
}
