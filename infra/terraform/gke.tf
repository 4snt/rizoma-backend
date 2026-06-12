# ── GKE Autopilot ─────────────────────────────────────────────────────────────
# Autopilot: sem gerenciamento de nós — Google cuida de escala, patches e HA.
# Custo: paga por pod (CPU/RAM solicitados), não por nó. Mínimo real: ~$50/mês
# com os workloads desta plataforma (api + r-worker + elasticsearch).

resource "google_container_cluster" "rizoma" {
  provider = google-beta

  name     = var.cluster_name
  location = var.region   # cluster regional → control plane multi-zona

  enable_autopilot = true

  network    = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.gke.id

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # Nós privados — sem IP público exposto nos workers
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false      # endpoint público do control plane (acesso via kubectl)
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }

  # Permite acesso ao control plane de qualquer origem
  # Restrinja a IPs fixos da equipe em produção real
  master_authorized_networks_config {
    cidr_blocks {
      cidr_block   = "0.0.0.0/0"
      display_name = "all"
    }
  }

  # Workload Identity: pods assumem permissões GCP sem service account key em arquivo
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  release_channel {
    channel = "REGULAR"
  }

  # Logging e monitoring gerenciados pelo GCP
  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
    managed_prometheus { enabled = true }
  }

  depends_on = [
    google_project_service.apis,
    google_compute_subnetwork.gke,
    google_service_networking_connection.sql_vpc,
  ]
}
