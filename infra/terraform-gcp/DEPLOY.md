# Deploy GCP — Passo a Passo

## Pré-requisitos

```bash
# Instalar ferramentas
brew install terraform google-cloud-sdk kubectl   # macOS
# ou via apt/snap no Linux

# Autenticar
gcloud auth login
gcloud auth application-default login
gcloud config set project SEU_PROJETO_GCP
```

## 1. Criar o projeto GCP (se ainda não existe)

```bash
gcloud projects create rizoma-tcc-XXXXX --name="Rizoma Bio-Platform"
gcloud billing projects link rizoma-tcc-XXXXX --billing-account=BILLING_ID
```

## 2. Configurar variáveis do Terraform

```bash
cp terraform.tfvars.example terraform.tfvars
# Edite terraform.tfvars com seu project_id, github_org, cors_origins, api_external_domain
```

## 3. Aplicar infraestrutura

```bash
terraform init
terraform plan   # revise o que será criado
terraform apply  # ~10-15 min (GKE Autopilot demora)
```

## 4. Configurar kubectl

```bash
$(terraform output -raw kubectl_command)
# equivale a: gcloud container clusters get-credentials rizoma --region southamerica-east1 --project SEU_PROJETO
```

## 5. Criar namespace e secrets Kubernetes

```bash
kubectl apply -f ../manifests/namespace.yaml

# Preencha GOOGLE_CLIENT_ID e JWT_SECRET antes de rodar:
eval "$(terraform output -raw create_k8s_secret_command | \
  sed 's/PREENCHA_GOOGLE_CLIENT_ID/SEU_CLIENT_ID/' | \
  sed 's/PREENCHA_JWT_SECRET/SEU_JWT_SECRET/')"
```

Ou crie manualmente:
```bash
kubectl create secret generic bio-secrets \
  --namespace=bioinformatica \
  --from-literal=POSTGRES_HOST=$(terraform output -raw db_private_ip) \
  --from-literal=POSTGRES_PORT=5432 \
  --from-literal=POSTGRES_DB=bioinformatica \
  --from-literal=POSTGRES_USER=api_user \
  --from-literal=POSTGRES_PASSWORD=$(terraform output -raw db_api_user_password) \
  --from-literal=POSTGRES_USER_RWORKER=r_worker \
  --from-literal=POSTGRES_PASSWORD_RWORKER=$(terraform output -raw db_r_worker_password) \
  --from-literal=ES_HOST=http://elasticsearch:9200 \
  --from-literal=GOOGLE_CLIENT_ID=SEU_CLIENT_ID \
  --from-literal=JWT_SECRET=SEU_JWT_SECRET \
  --from-literal=ALLOWED_EMAIL_DOMAIN=@ufvjm.edu.br \
  --from-literal=JWT_ACCESS_MINUTES=60 \
  --from-literal=CORS_ORIGINS=https://rizoma.vercel.app
```

## 6. Criar IP estático para o Load Balancer

```bash
gcloud compute addresses create bio-api-ip --global --project SEU_PROJETO
gcloud compute addresses describe bio-api-ip --global --format="value(address)"
# Aponte o DNS do seu domínio para este IP
```

## 7. Aplicar manifests Kubernetes

Edite `manifests/api-deployment.yaml` e `manifests/ingress.yaml`:
- Substitua `PROJECT_ID` pelo seu projeto GCP
- Substitua `bioapi.seu-dominio.com` pelo domínio real

```bash
# Substitui placeholders de imagem e aplica
AR_URL="southamerica-east1-docker.pkg.dev/SEU_PROJETO/bio-platform"

sed "s|IMAGE_PLACEHOLDER_API|${AR_URL}/bio-platform-api:latest|g" \
  ../manifests/api-deployment.yaml | kubectl apply -f -

sed "s|IMAGE_PLACEHOLDER_RWORKER|${AR_URL}/bio-platform-rworker:latest|g" \
  ../manifests/r-worker-deployment.yaml | kubectl apply -f -

kubectl apply -f ../manifests/elasticsearch.yaml
kubectl apply -f ../manifests/ingress.yaml
```

## 8. Configurar GitHub Actions Variables

No repositório GitHub → Settings → Variables → Actions:

| Variable | Valor |
|----------|-------|
| `GCP_PROJECT_ID` | ID do projeto GCP |
| `GCP_WIF_PROVIDER` | `terraform output -raw workload_identity_provider` |
| `GCP_CI_SA` | `terraform output -raw github_actions_sa` |

Nenhum secret de SA key necessário — usa Workload Identity.

## 9. Deploy inicial via CI

```bash
git commit --allow-empty -m "ci: trigger initial GCP deploy"
git push
```

## Referência rápida

```bash
# Logs da API
kubectl logs -f deployment/bio-api -n bioinformatica

# Logs do R Worker
kubectl logs -f deployment/bio-r-worker -n bioinformatica

# Status dos pods
kubectl get pods -n bioinformatica

# Ver senhas do banco
terraform output -raw db_api_user_password
terraform output -raw db_r_worker_password

# Resetar deployment manualmente
kubectl rollout restart deployment/bio-api -n bioinformatica
kubectl rollout restart deployment/bio-r-worker -n bioinformatica
```

## Estimativa de custo (southamerica-east1)

| Recurso | Configuração | ~Custo/mês |
|---------|-------------|------------|
| GKE Autopilot | api (0.2 CPU/256MB) + r-worker (1 CPU/3GB) + ES (0.5 CPU/1.5GB) | ~$60 |
| Cloud SQL | db-custom-2-4096, 30GB SSD | ~$75 |
| Artifact Registry | ~5 imagens × 3 versões × ~500MB | ~$3 |
| NAT + LB + tráfego | baixo volume acadêmico | ~$15 |
| **Total estimado** | | **~$150/mês** |

Para reduzir custos em dev, use `db_tier = "db-f1-micro"` (~$7/mês, sem HA).
