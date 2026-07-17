resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${local.name}-db" }
}

# rds.force_ssl=0: a conexão app->RDS não sai da VPC (RDS não é público e o SG
# só libera as tasks). O runtime usa asyncpg sem sslmode; forçar SSL exigiria
# empacotar o CA do RDS na imagem. Traffic interno + SG restrito = aceitável.
resource "aws_db_parameter_group" "pg16" {
  name   = "${local.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "0"
  }
}

resource "aws_db_instance" "main" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = "16"

  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_master_username
  password = var.db_master_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.pg16.name
  publicly_accessible    = false

  multi_az                = false
  backup_retention_period = 7
  skip_final_snapshot     = true
  deletion_protection     = false

  # PostGIS: a extensão é criada pela migration baseline (CREATE EXTENSION
  # postgis). O usuário mestre do RDS tem rds_superuser, que pode fazê-lo.
  apply_immediately = true

  tags = { Name = local.name }
}
