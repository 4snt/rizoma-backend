output "ingress_nodeport_http" {
  value       = 30080
  description = "Porta no host onde o Traefik do MicroK8s escuta HTTP — o Traefik do docker-compose encaminha pra cá."
}

output "namespace" {
  value = kubernetes_namespace.bioinformatica.metadata[0].name
}
