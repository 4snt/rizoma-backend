terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # Backend remoto recomendado em equipe. Descomente e ajuste o bucket/lock:
  # backend "s3" {
  #   bucket         = "rizoma-tfstate"
  #   key            = "rizoma/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "rizoma-tflock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
