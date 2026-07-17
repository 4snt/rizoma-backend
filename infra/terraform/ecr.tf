locals {
  ecr_repos = ["api", "rworker", "frontend"]
}

resource "aws_ecr_repository" "repo" {
  for_each             = toset(local.ecr_repos)
  name                 = "${var.project_name}/${each.key}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Mantém só as 10 imagens mais recentes por repo — imagem de container
# Bioconductor é grande e o armazenamento no ECR é cobrado.
resource "aws_ecr_lifecycle_policy" "expire_untagged" {
  for_each   = aws_ecr_repository.repo
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Manter só as 10 imagens mais recentes"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      }
    ]
  })
}
