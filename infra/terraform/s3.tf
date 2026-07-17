locals {
  # Bucket precisa ser único globalmente; sufixo com account id evita colisão.
  bucket_name = "${var.project_name}-${var.environment}-storage-${data.aws_caller_identity.current.account_id}"
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "storage" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "storage" {
  bucket                  = aws_s3_bucket.storage.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "storage" {
  bucket = aws_s3_bucket.storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "storage" {
  bucket = aws_s3_bucket.storage.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# CORS: o upload é presigned POST direto do browser para o S3. Sem isto o
# browser bloqueia o PUT/POST cross-origin.
resource "aws_s3_bucket_cors_configuration" "storage" {
  bucket = aws_s3_bucket.storage.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST", "HEAD"]
    allowed_origins = compact([
      var.app_domain != "" ? "https://${var.app_domain}" : "",
      "http://localhost:3000",
    ])
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}
