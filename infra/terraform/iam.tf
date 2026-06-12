# ── Service Account para workloads GKE ───────────────────────────────────────
# Pods que precisam de permissões GCP usam Workload Identity —
# sem montar service account key como volume/secret.

resource "google_service_account" "workload" {
  account_id   = "rizoma-workload"
  display_name = "Rizoma GKE Workload SA"
  description  = "SA assumida pelos pods via Workload Identity"
}

# Binding: K8s ServiceAccount → GCP SA
# K8s SA "rizoma-workload" no namespace "bioinformatica" pode agir como este SA GCP.
resource "google_service_account_iam_member" "workload_identity" {
  service_account_id = google_service_account.workload.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.namespace}/rizoma-workload]"
}

# ── Service Account para GitHub Actions ──────────────────────────────────────

resource "google_service_account" "github_actions" {
  account_id   = "github-actions"
  display_name = "GitHub Actions CI/CD"
  description  = "Push de imagens ao Artifact Registry + deploy ao GKE"
}

resource "google_project_iam_member" "ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

resource "google_project_iam_member" "gke_developer" {
  project = var.project_id
  role    = "roles/container.developer"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

# ── Workload Identity Federation para GitHub Actions ─────────────────────────
# Permite que o CI se autentique sem service account key (sem segredo para vazar).

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions Pool"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub OIDC"

  # Só aceita tokens do repositório configurado
  attribute_condition = "assertion.repository == '${var.github_org}/${var.github_repo}'"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# GitHub Actions pode impersonar o SA de CI
resource "google_service_account_iam_member" "github_wif" {
  service_account_id = google_service_account.github_actions.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_org}/${var.github_repo}"
}

# ── GKE acessa Artifact Registry (pull de imagens) ───────────────────────────
# O SA padrão dos nós do GKE precisa de leitura no AR.

data "google_compute_default_service_account" "default" {
  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "node_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${data.google_compute_default_service_account.default.email}"
}
