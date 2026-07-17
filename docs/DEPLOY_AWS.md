# Deploy na AWS (ECS Fargate + RDS + S3)

Substitui o fluxo antigo (GHCR + Coolify). A infra é descrita em Terraform em
`infra/terraform/` e o deploy contínuo roda pelo GitHub Actions
(`.github/workflows/build.yml`): build das imagens → push no ECR →
`ecs update-service --force-new-deployment`.

## Topologia

```
                        Internet
                           │
                    ┌──────▼───────┐
                    │     ALB      │  :80 / :443 (ACM opcional)
                    └──┬────────┬──┘
          path /api/v1,│        │ resto
          /health,/docs│        │
                 ┌──────▼─┐  ┌──▼────────┐
                 │  api   │  │ frontend  │   ECS Fargate (subnets públicas)
                 │ :8000  │  │  :3000    │
                 └───┬────┘  └───────────┘
                     │            r-worker (Fargate, sem ALB)
        ┌────────────┼────────────────┐
        ▼            ▼                 ▼
   RDS Postgres   S3 bucket      SSM Parameter Store
   16 + PostGIS   (object)       (segredos → env da task)
   (subnet priv)
```

Decisões de custo (é um TCC, não um SaaS):
- **Sem NAT Gateway.** As tasks Fargate ficam em subnet pública com IP público e
  puxam imagem do ECR / falam com S3 e CloudWatch pela internet. Os SGs travam a
  entrada (só o ALB alcança as tasks; só as tasks alcançam o RDS).
- **RDS single-AZ `db.t4g.micro`**, storage gp3 com autoscaling até 100 GB.
- **SSM Parameter Store** (SecureString) em vez de Secrets Manager.

## Pré-requisitos

- Conta AWS + AWS CLI autenticado (`aws sts get-caller-identity`).
- Terraform >= 1.6.
- Repositório GitHub `4snt/rizoma-backend` (backend) e `4snt/rizoma` (frontend).

## 1. Provisionar a infra

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# edite terraform.tfvars: senhas, segredos, (opcional) domínios + ACM
terraform init
terraform apply
```

Outputs relevantes:

| Output | Uso |
|--------|-----|
| `alb_dns_name` | aponte seu DNS (CNAME) para cá |
| `public_base_url` | URL pública (frontend + API no mesmo host) |
| `ecr_repositories` | URLs dos repos ECR |
| `ecs_cluster` | nome do cluster (CI usa no deploy) |
| `rds_endpoint` | host:porta do Postgres |
| `s3_bucket` | bucket de storage |
| `build_time_frontend_env` | valores `NEXT_PUBLIC_*` para o CI |

> **HTTPS:** deixe `acm_certificate_arn` vazio para subir só em HTTP e validar.
> Para produção, crie um certificado no ACM (mesma região) cobrindo seus hosts,
> cole o ARN, e defina `app_domain`/`api_domain`. O ALB passa a redirecionar
> 80→443.

## 2. Configurar o GitHub Actions (backend `4snt/rizoma-backend`)

O CI autentica na AWS via **OIDC** (sem chaves estáticas). Crie uma role IAM
confiando no provedor OIDC do GitHub, com permissão de push no ECR e
`ecs:UpdateService`/`ecs:DescribeServices` no cluster.

**Secrets:**
| Nome | Valor |
|------|-------|
| `AWS_ROLE_ARN` | ARN da role OIDC |

**Variables:**
| Nome | Valor (exemplo) |
|------|------|
| `AWS_REGION` | `us-east-1` |
| `ECR_REGISTRY` | `<account>.dkr.ecr.us-east-1.amazonaws.com` |
| `ECS_CLUSTER` | `rizoma-prod` |
| `NEXT_PUBLIC_API_URL` | `public_base_url` do Terraform |
| `NEXT_PUBLIC_WS_URL` | idem, com `wss://` |

> Os `NEXT_PUBLIC_*` são **embutidos no bundle em build-time** — por isso vêm de
> variáveis do CI, não da task ECS. Se mudar o domínio, rebuild o frontend.

## 3. Primeiro deploy

`git push` no `master` dispara o `build.yml`: build+push das 3 imagens e
`--force-new-deployment` das 3 services. A task da **api** roda
`alembic upgrade head` no start — isso cria o schema, as extensões
(`postgis`, `pg_trgm`, `pgcrypto`) e os papéis `rizoma_app` / `rizoma_system`
no RDS antes de subir o uvicorn.

Rebuild manual: aba **Actions → Build & Deploy (AWS) → Run workflow**.

## Object storage: MinIO → S3 nativo

O código (`app/shared/storage.py`, boto3) já falava "S3". A adaptação para a AWS:

- `S3_ENDPOINT` / `S3_PUBLIC_ENDPOINT` **vazios** → boto3 usa o endpoint
  regional nativo do S3.
- `S3_ACCESS_KEY` / `S3_SECRET_KEY` **vazios** → boto3 pega credenciais da
  **IAM role da task** (nenhuma chave estática em produção).
- `S3_BUCKET` / `S3_REGION` vêm do Terraform.

O bucket tem CORS liberado para o host do frontend (upload é presigned POST
direto do browser).

## Papéis do Postgres

As senhas de `rizoma_app` / `rizoma_system` agora vêm de `APP_DB_PASSWORD` /
`SYSTEM_DB_PASSWORD` (a migration baseline as aplica; antes eram hardcoded). O
RDS não é público e o SG só libera as tasks, mas prefira segredos fortes.

## Rollback

O CI publica também a tag `:<sha>`. Para voltar uma versão, registre uma task
definition apontando para a tag antiga e faça `update-service`, ou reverta o
commit e deixe o CI rodar.

## Custo aproximado (us-east-1, sob demanda)

| Recurso | Ordem de grandeza/mês |
|---------|----------------------|
| ALB | ~US$18 |
| RDS db.t4g.micro | ~US$13 + storage |
| Fargate api (0.5 vCPU/1GB) | ~US$18 |
| Fargate frontend (0.25/0.5) | ~US$9 |
| Fargate r-worker (1 vCPU/4GB) | ~US$36 (24/7) |
| S3 + ECR + logs | poucos US$ |

> O r-worker é o item mais caro rodando 24/7. Como ele só processa jobs da fila,
> dá para reduzir `worker_desired_count = 0` e subir sob demanda, ou migrá-lo
> depois para uma execução event-driven. Fora do escopo desta entrega.
