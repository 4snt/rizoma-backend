resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "svc" {
  for_each          = toset(["api", "frontend"])
  name              = "/ecs/${local.name}/${each.key}"
  retention_in_days = var.log_retention_days
}

locals {
  scheme   = local.https_enabled ? "https" : "http"
  app_host = var.app_domain != "" ? var.app_domain : aws_lb.main.dns_name
  ws_scheme = local.https_enabled ? "wss" : "ws"

  # Frontend e API compartilham o mesmo host no ALB (roteamento por path).
  public_base = "${local.scheme}://${local.app_host}"
  ws_base     = "${local.ws_scheme}://${local.app_host}"

  # Env comum aos serviços: conexão com o RDS e com o S3. Endpoints S3 vazios
  # => boto3/aws.s3 usam o endpoint regional nativo e a IAM role da task.
  db_env = [
    { name = "POSTGRES_HOST", value = aws_db_instance.main.address },
    { name = "POSTGRES_PORT", value = "5432" },
    { name = "POSTGRES_DB", value = var.db_name },
    { name = "POSTGRES_USER", value = var.db_master_username },
    { name = "APP_DB_USER", value = "rizoma_app" },
    { name = "SYSTEM_DB_USER", value = "rizoma_system" },
  ]

  s3_env = [
    { name = "S3_ENDPOINT", value = "" },
    { name = "S3_PUBLIC_ENDPOINT", value = "" },
    { name = "S3_ACCESS_KEY", value = "" },
    { name = "S3_SECRET_KEY", value = "" },
    { name = "S3_BUCKET", value = aws_s3_bucket.storage.bucket },
    { name = "S3_REGION", value = var.aws_region },
  ]

  db_secrets = [
    { name = "POSTGRES_PASSWORD", valueFrom = aws_ssm_parameter.secret["db_master_password"].arn },
    { name = "APP_DB_PASSWORD", valueFrom = aws_ssm_parameter.secret["app_db_password"].arn },
    { name = "SYSTEM_DB_PASSWORD", valueFrom = aws_ssm_parameter.secret["system_db_password"].arn },
  ]
}

# ─────────────────────────────── API ────────────────────────────────
resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.repo["api"].repository_url}:${var.image_tag}"
      essential = true
      # Migration (cria schema + papéis + extensões) e depois o servidor.
      command = ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]
      environment = concat(local.db_env, local.s3_env, [
        { name = "CORS_ORIGINS", value = local.public_base },
        { name = "GOOGLE_CLIENT_ID", value = var.google_client_id },
        { name = "ALLOWED_EMAIL_DOMAIN", value = var.allowed_email_domain },
        { name = "LOG_LEVEL", value = "info" },
      ])
      secrets = concat(local.db_secrets, [
        { name = "JWT_SECRET", valueFrom = aws_ssm_parameter.secret["jwt_secret"].arn },
      ])
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.svc["api"].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}


# ─────────────────────────────── Frontend ───────────────────────────
resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = "${aws_ecr_repository.repo["frontend"].repository_url}:${var.image_tag}"
      essential = true
      portMappings = [{ containerPort = 3000, protocol = "tcp" }]
      environment = [
        { name = "NODE_ENV", value = "production" },
        { name = "HOSTNAME", value = "0.0.0.0" },
        { name = "PORT", value = "3000" },
        { name = "NEXTAUTH_URL", value = local.public_base },
        { name = "API_URL", value = local.public_base },
        { name = "GOOGLE_CLIENT_ID", value = var.google_client_id },
        { name = "ALLOWED_EMAIL_DOMAIN", value = var.allowed_email_domain },
      ]
      secrets = [
        { name = "AUTH_SECRET", valueFrom = aws_ssm_parameter.secret["auth_secret"].arn },
        { name = "NEXTAUTH_SECRET", valueFrom = aws_ssm_parameter.secret["auth_secret"].arn },
        { name = "GOOGLE_CLIENT_SECRET", valueFrom = aws_ssm_parameter.secret["google_client_secret"].arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.svc["frontend"].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "frontend"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "frontend" {
  name            = "frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.frontend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 3000
  }

  depends_on = [aws_lb_listener.http]
}
