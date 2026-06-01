library(aws.s3)

minio_setup <- function() {
  Sys.setenv(
    AWS_ACCESS_KEY_ID     = Sys.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    AWS_SECRET_ACCESS_KEY = Sys.getenv("MINIO_SECRET_KEY", "changeme"),
    AWS_DEFAULT_REGION    = ""   # vazio evita prefixo de região no hostname do MinIO
  )
}

minio_download_rds <- function(bucket, key, local_path) {
  minio_setup()
  aws.s3::save_object(
    object    = key,
    bucket    = bucket,
    file      = local_path,
    base_url  = Sys.getenv("MINIO_ENDPOINT", "minio:9000"),
    use_https = FALSE,
    region    = ""
  )
  readRDS(local_path)
}

minio_upload_rds <- function(obj, bucket, key) {
  minio_setup()
  tmp <- tempfile(fileext = ".rds")
  saveRDS(obj, tmp)
  on.exit(unlink(tmp))
  aws.s3::put_object(
    file      = tmp,
    object    = key,
    bucket    = bucket,
    base_url  = Sys.getenv("MINIO_ENDPOINT", "minio:9000"),
    use_https = FALSE,
    region    = ""
  )
}
