# ── Artifact Registry ─────────────────────────────────────────────────────────
# Repositório Docker regional para as imagens da plataforma.
# URL resultante: southamerica-east1-docker.pkg.dev/PROJECT/bio-platform/IMAGE:TAG

resource "google_artifact_registry_repository" "bio" {
  location      = var.region
  repository_id = var.ar_repository
  format        = "DOCKER"
  description   = "Bio-platform container images (api, postgres)"
  depends_on    = [google_project_service.apis]

  cleanup_policies {
    id     = "keep-last-5"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }
}
