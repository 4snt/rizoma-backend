#!/usr/bin/env Rscript
# upload_phyloseq_to_minio.R
#
# Faz upload de um arquivo .rds para o bucket pipeline-artifacts do MinIO.
# Uso:
#   Rscript upload_phyloseq_to_minio.R <local_rds> <project_code> [minio_host]
#
# Exemplo:
#   Rscript upload_phyloseq_to_minio.R /tmp/INOVAHERB_ITS.rds INOVAHERB
#   Rscript upload_phyloseq_to_minio.R /tmp/INOVAHERB_ITS.rds INOVAHERB localhost:9000

suppressPackageStartupMessages(library(aws.s3))

args <- commandArgs(trailingOnly=TRUE)
if (length(args) < 2) {
  cat("Uso: Rscript upload_phyloseq_to_minio.R <rds_path> <project_code> [minio_host]\n")
  quit(status=1)
}

local_rds    <- args[1]
project_code <- args[2]
minio_host   <- if (length(args) >= 3) args[3] else Sys.getenv("MINIO_ENDPOINT", "localhost:9000")

# Credenciais
Sys.setenv(
  AWS_ACCESS_KEY_ID     = Sys.getenv("MINIO_ACCESS_KEY", "minioadmin"),
  AWS_SECRET_ACCESS_KEY = Sys.getenv("MINIO_SECRET_KEY", "changeme"),
  AWS_DEFAULT_REGION    = "us-east-1"
)

bucket     <- "pipeline-artifacts"
object_key <- paste0(project_code, "/phyloseq.rds")

message(sprintf("Enviando %s → s3://%s/%s via %s", local_rds, bucket, object_key, minio_host))

aws.s3::put_object(
  file      = local_rds,
  object    = object_key,
  bucket    = bucket,
  base_url  = minio_host,
  use_https = FALSE
)

message(sprintf("Upload concluído: pipeline-artifacts/%s", object_key))
message(sprintf("phyloseq_key para usar no enqueue: pipeline-artifacts/%s", object_key))
