# Guia de Deploy — Coolify

> Coolify é uma plataforma self-hosted de deploy (alternativa ao Heroku/Railway).
> Neste projeto, ele gerencia o build e deploy dos serviços a partir dos repositórios GitHub.

---

## 1. Arquitetura de deploy

```
GitHub
  ├── bio-platform   (FastAPI + R Worker + DB migrations)
  └── bio-frontend   (Next.js)
         │
         ▼ webhook push
      Coolify Server
         │
         ├── bio-platform-api    → porta 8000
         ├── bio-frontend        → porta 3000
         ├── PostgreSQL 16       → porta 5432 (interno)
         ├── Elasticsearch 8     → porta 9200 (interno)
         ├── MinIO               → porta 9000/9001
         └── R Worker            → sem porta (consumer de fila)
```

**Topologia recomendada:**
- Coolify roda num servidor separado (ou no nó `server` do k3s)
- Os serviços rodam no mesmo servidor via Docker Compose (dev/staging)
- Para produção, os manifests k3s em `infra/manifests/` continuam sendo a opção

---

## 2. Instalação do Coolify

```bash
# No servidor de destino (Ubuntu 22.04+, mínimo 2 vCPU, 2GB RAM)
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

Acesse `http://<ip-do-servidor>:8000` e crie a conta inicial.

---

## 3. Conectar os repositórios GitHub

### 3.1 Source — GitHub App

Em Coolify: **Sources → GitHub App → Install on GitHub**

Autorize o acesso aos repositórios:
- `4snt/bio-platform`
- `4snt/bio-frontend`

### 3.2 Criar Projeto unificado no Coolify

**Projects → New Project → "Bio-Platform TCC"**

Todos os serviços ficam dentro deste projeto, compartilhando a mesma rede Docker.

---

## 4. Configurar cada serviço

### 4.1 PostgreSQL (Database)

**Resources → New → Database → PostgreSQL 16**

| Campo | Valor |
|-------|-------|
| Nome | `bio-postgres` |
| Database | `bioinformatica` |
| Usuário | `api_user` |
| Senha | (gerar no Coolify) |

Após criar, copie a **Internal URL** (ex: `postgresql://api_user:xxx@bio-postgres:5432/bioinformatica`).

> As migrations rodam automaticamente via `docker-entrypoint-initdb.d`. Configure o volume mount para `./db/migrations:/docker-entrypoint-initdb.d` no serviço.

### 4.2 Elasticsearch (Database)

**Resources → New → Database → Elasticsearch**

| Campo | Valor |
|-------|-------|
| Nome | `bio-elasticsearch` |
| Variáveis | `discovery.type=single-node`, `xpack.security.enabled=false`, `ES_JAVA_OPTS=-Xms512m -Xmx512m` |

### 4.3 MinIO (Service)

**Resources → New → Service → MinIO**

| Campo | Valor |
|-------|-------|
| Nome | `bio-minio` |
| Root user | `minioadmin` |
| Root password | (gerar) |
| Console port | `9001` |

### 4.4 FastAPI — bio-platform API

**Resources → New → Application → bio-platform**

| Campo | Valor |
|-------|-------|
| Source | GitHub App → `4snt/bio-platform` |
| Branch | `master` |
| Build pack | `Dockerfile` |
| Dockerfile path | `api/Dockerfile` |
| Porta | `8000` |
| Domínio | `api.bio.local` (ou seu domínio real) |

**Environment Variables:**
```
POSTGRES_HOST=bio-postgres
POSTGRES_PORT=5432
POSTGRES_DB=bioinformatica
POSTGRES_USER=api_user
POSTGRES_PASSWORD=<gerado-no-passo-4.1>
ES_HOST=http://bio-elasticsearch:9200
MINIO_ENDPOINT=bio-minio:9000
MINIO_PUBLIC_ENDPOINT=<ip-publico-ou-dominio>:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=<gerado-no-passo-4.3>
MINIO_SECURE=false
JWT_SECRET=<string-aleatoria-longa>
JWT_ACCESS_MINUTES=30
JWT_REFRESH_DAYS=7
LOG_LEVEL=info
```

### 4.5 R Worker — bio-platform R Worker

**Resources → New → Application → bio-r-worker**

| Campo | Valor |
|-------|-------|
| Source | GitHub App → `4snt/bio-platform` |
| Branch | `master` |
| Build pack | `Dockerfile` |
| Dockerfile path | `r-worker/Dockerfile` |
| Porta | nenhuma (sem HTTP) |
| Start command | `Rscript worker.R` |

**Environment Variables:** (mesmas do API, sem JWT)
```
POSTGRES_HOST=bio-postgres
POSTGRES_PORT=5432
POSTGRES_DB=bioinformatica
POSTGRES_USER=r_worker
POSTGRES_PASSWORD=changeme
ES_HOST=http://bio-elasticsearch:9200
MINIO_ENDPOINT=bio-minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=<gerado-no-passo-4.3>
MINIO_SECURE=false
```

> O R Worker não tem health check HTTP. Configure **Health Check → Disabled** no Coolify.

### 4.6 Next.js — bio-frontend

**Resources → New → Application → bio-frontend**

| Campo | Valor |
|-------|-------|
| Source | GitHub App → `4snt/bio-frontend` |
| Branch | `master` |
| Build pack | `Dockerfile` |
| Porta | `3000` |
| Domínio | `bio.local` (ou seu domínio real) |

**Environment Variables:**
```
NEXT_PUBLIC_API_URL=https://api.bio.local
NEXT_PUBLIC_WS_URL=wss://api.bio.local
NEXTAUTH_URL=https://bio.local
NEXTAUTH_SECRET=<string-aleatoria>
```

**Build Args** (para Next.js standalone output):
```
NODE_ENV=production
```

> Adicione ao `bio-frontend/Dockerfile` (multi-stage) se ainda não existir:
> ```dockerfile
> FROM node:20-alpine AS builder
> WORKDIR /app
> COPY package*.json ./
> RUN npm ci
> COPY . .
> RUN npm run build
>
> FROM node:20-alpine AS runner
> WORKDIR /app
> ENV NODE_ENV production
> COPY --from=builder /app/.next/standalone ./
> COPY --from=builder /app/.next/static ./.next/static
> COPY --from=builder /app/public ./public
> EXPOSE 3000
> CMD ["node", "server.js"]
> ```
> E em `next.config.js`: `output: 'standalone'`

---

## 5. Deploy automático (CI/CD)

No Coolify, cada serviço tem um **Webhook URL**. Configure no GitHub:

**bio-platform:** Settings → Webhooks → Add webhook
```
Payload URL: https://<coolify>/api/v1/deploy/webhook?token=<token>&uuid=<uuid>
Content type: application/json
Events: Push events → master branch
```

**bio-frontend:** idem com o webhook do serviço frontend.

A partir daí, qualquer `git push master` dispara o rebuild automático.

---

## 6. Centralizar os dois repos no mesmo GitHub Project

Como o token atual não tem escopo `project`, rode uma vez:

```bash
# 1. Adicionar escopo ao token
gh auth refresh -s project,read:project

# 2. Criar o projeto
gh project create --owner 4snt --title "Bio-Platform TCC"
# → anote o número do projeto (ex: 1)

# 3. Linkar os dois repos
gh project link 1 --owner 4snt --repo 4snt/bio-platform
gh project link 1 --owner 4snt --repo 4snt/bio-frontend
```

No GitHub Projects você pode criar colunas:
- **Backlog** — tarefas planejadas
- **Em desenvolvimento** — PRs abertos
- **Revisão** — aguardando merge
- **Concluído** — done

Issues e PRs de ambos os repos aparecem no mesmo board.

---

## 7. Variáveis sensíveis — não commitar

Nunca commite no git:
- `JWT_SECRET`
- `NEXTAUTH_SECRET`
- `POSTGRES_PASSWORD`
- `MINIO_SECRET_KEY`

No Coolify: **Project → Environment Variables → Shared** — defina uma vez e todos os serviços herdam.

No k3s: use um Secret:
```bash
kubectl create secret generic bio-secrets \
  --from-literal=JWT_SECRET=xxx \
  --from-literal=NEXTAUTH_SECRET=xxx \
  --from-literal=POSTGRES_PASSWORD=xxx \
  --from-literal=MINIO_SECRET_KEY=xxx
```

---

## 8. Checklist de primeiro deploy

- [ ] Coolify instalado e acessível
- [ ] GitHub App autorizado nos 2 repos
- [ ] PostgreSQL criado + Internal URL copiada
- [ ] Migrations aplicadas (verificar logs do container)
- [ ] MinIO criado + buckets criados (a API faz isso no startup via `ensure_buckets()`)
- [ ] Elasticsearch criado
- [ ] API deployada e `/health` retornando `{"status":"ok"}`
- [ ] R Worker deployado e logs mostrando `[worker] Aguardando jobs...`
- [ ] Frontend deployado e acessível no domínio
- [ ] Seed do primeiro usuário admin executado
- [ ] Login funcionando
- [ ] Webhooks configurados nos dois repos
