# ── VPC ───────────────────────────────────────────────────────────────────────

resource "google_compute_network" "vpc" {
  name                    = "rizoma-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

# ── Sub-rede do GKE ───────────────────────────────────────────────────────────
# Ranges secundários obrigatórios para Autopilot

resource "google_compute_subnetwork" "gke" {
  name          = "rizoma-gke"
  ip_cidr_range = "10.10.0.0/20"   # nós
  region        = var.region
  network       = google_compute_network.vpc.id

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/16" # /16 = 65 536 IPs — suficiente para Autopilot
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/20" # /20 = 4 096 services
  }

  private_ip_google_access = true # permite acesso às APIs Google sem NAT
}

# ── NAT ───────────────────────────────────────────────────────────────────────
# Nós privados do GKE precisam de NAT para saída à internet:
# NCBI SRA, ENA, FUNGuild (mycoportal.org), pip/CRAN installs no build

resource "google_compute_router" "nat_router" {
  name    = "rizoma-router"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "nat" {
  name                               = "rizoma-nat"
  router                             = google_compute_router.nat_router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# ── VPC Peering para Cloud SQL (IP privado) ───────────────────────────────────

resource "google_compute_global_address" "sql_peering" {
  name          = "rizoma-sql-peering"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
  depends_on    = [google_project_service.apis]
}

resource "google_service_networking_connection" "sql_vpc" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_peering.name]
  depends_on              = [google_project_service.apis]
}

# ── Firewall ──────────────────────────────────────────────────────────────────

# Health checks do GCP Load Balancer
resource "google_compute_firewall" "allow_health_checks" {
  name    = "rizoma-allow-health-checks"
  network = google_compute_network.vpc.name

  allow { protocol = "tcp" }

  # Ranges oficiais dos health checkers do Google
  source_ranges = ["130.211.0.0/22", "35.191.0.0/16"]
}

# Tráfego interno entre pods
resource "google_compute_firewall" "allow_internal" {
  name    = "rizoma-allow-internal"
  network = google_compute_network.vpc.name

  allow { protocol = "tcp" }
  allow { protocol = "udp" }
  allow { protocol = "icmp" }

  source_ranges = [
    "10.10.0.0/20",
    "10.20.0.0/16",
    "10.30.0.0/20",
  ]
}
