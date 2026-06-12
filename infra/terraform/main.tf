terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Descomente após criar o bucket manualmente:
  # gcloud storage buckets create gs://PROJETO-tfstate --location=southamerica-east1
  #
  # backend "gcs" {
  #   bucket = "SEU_PROJETO-tfstate"
  #   prefix = "bio-platform"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# ── APIs necessárias ──────────────────────────────────────────────────────────
resource "google_project_service" "apis" {
  for_each = toset([
    "container.googleapis.com",               # GKE
    "sqladmin.googleapis.com",                # Cloud SQL
    "servicenetworking.googleapis.com",       # VPC peering (Cloud SQL private IP)
    "artifactregistry.googleapis.com",        # Artifact Registry
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",          # Workload Identity
    "sts.googleapis.com",                     # Security Token Service (WIF)
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}
