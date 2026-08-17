# Rizoma — backend

Plataforma de análise de micobioma e transcriptômica (TCC de bioinformática, UFVJM).

Este repositório contém a **API** (FastAPI), o **R Worker** (Bioconductor: ANCOM-BC2,
MaAsLin2, DESeq2, SpiecEasi, phyloseq, vegan) e a infraestrutura de desenvolvimento.

O banco é PostgreSQL 16 + PostGIS. Os arquivos (FASTQ e artefatos) ficam em object
storage S3 (MinIO), nunca dentro do banco. A fila de jobs é o próprio Postgres
(`LISTEN/NOTIFY` + `FOR UPDATE SKIP LOCKED`) — sem Redis, sem Celery.

---

## Subir em 3 comandos

```bash
cp .env.example .env      # ajuste o que precisar; os defaults funcionam em dev
make up                   # postgres + minio + api (a API roda as migrations sozinha)
make logs                 # acompanha
```

- API: <http://localhost:8000> · docs interativos em `/docs`
- Console do MinIO: <http://localhost:9001>

O **R Worker fica de fora do `make up`** de propósito: a imagem Bioconductor leva
cerca de 20 minutos para compilar. Quando precisar dele:

```bash
make up-worker
```

`make` sem argumento lista todos os alvos (`migrate`, `migration`, `test`, `psql`,
`reset`, `seed`, ...).

---

## Os dois papéis de banco (leia antes de mexer no banco)

Não é firula. É o que faz o isolamento entre organizações existir de verdade.

| Papel | Atributos | Quem usa |
|---|---|---|
| `api_user` | dono do schema | **só as migrations** (Alembic) |
| `rizoma_app` | `NOSUPERUSER NOBYPASSRLS` | **o runtime da API** |
| `rizoma_system` | `BYPASSRLS` | login, reaper de jobs, verificação pública de laudo |

Toda tabela tem `organization_id` e tem Row-Level Security ligada. A policy compara
esse campo com um parâmetro definido por transação.

O motivo do `rizoma_app` ser **NOSUPERUSER**: no Postgres, **superusuário ignora RLS
em silêncio**. A policy continua no catálogo, os testes passam, e o isolamento
simplesmente não acontece. Rodar a API como superusuário é ter RLS de enfeite.

E o parâmetro da organização é definido com **`SET LOCAL`**, dentro da transação —
nunca `SET` puro. Com pool de conexões, um `SET` sobrevive ao fim da requisição e a
próxima requisição herda a organização da anterior. É vazamento cross-tenant
silencioso.

Quem precisa legitimamente cruzar organizações (achar o usuário no login, antes de
saber a org dele) usa o papel `rizoma_system`. **Não existe "GUC de bypass"** — um
`SET app.bypass_rls = true` seria burlável, porque qualquer usuário pode setar um GUC
customizado. Bypass tem que ser atributo de papel.

Os papéis `rizoma_app` e `rizoma_system` são criados pela própria migration baseline.

Detalhes: [ADR-007](docs/decisions/ADR-007-uuidv7-rls.md).

---

## Migrations

Alembic. O runner de `.sql` caseiro foi aposentado — os arquivos antigos estão em
`docs/legacy-migrations/`, só como histórico ([ADR-002](docs/decisions/ADR-002-alembic.md)).

```bash
make migrate                          # alembic upgrade head
make migration m="add samples table"  # cria uma revisão nova
```

O container da API roda `alembic upgrade head` antes de subir o uvicorn, então em dev
você raramente precisa chamar isso à mão.

O Alembic usa driver **síncrono** (`psycopg`) e o papel **dono do schema**; o runtime
usa `asyncpg` e o papel `rizoma_app`. São duas DSNs distintas em `app/core/config.py`,
e a separação é proposital.

---

## Testes

```bash
make test              # dentro do container
# ou, localmente:
cd api && pytest
cd api && pytest tests/test_foo.py
```

O teste de isolamento multi-tenant é obrigatório: se ele quebrar, alguém tornou a RLS
decorativa.

---

## Object storage: os dois endpoints S3

Causa nº 1 de `403` no upload. São dois, e são diferentes:

- `S3_ENDPOINT` — por onde **a API** fala com o MinIO. Na rede do Compose: `http://minio:9000`.
- `S3_PUBLIC_ENDPOINT` — o host que vai **assinado** na presigned URL. Quem faz o PUT é
  o **browser**, e o browser não resolve o nome `minio`. Em dev: `http://localhost:9000`.

A assinatura V4 cobre o header `Host`. Assinar com o host interno e acessar pelo
externo devolve 403. Ver [ADR-001](docs/decisions/ADR-001-object-storage.md).

---

## Decisões de arquitetura

Estão em [`docs/decisions/`](docs/decisions/), uma por arquivo:

| ADR | Decisão |
|---|---|
| [001](docs/decisions/ADR-001-object-storage.md) | MinIO + presigned URL; sair dos PG Large Objects |
| [002](docs/decisions/ADR-002-alembic.md) | Alembic desde já |
| [003](docs/decisions/ADR-003-no-elasticsearch.md) | Elasticsearch fora do MVP (Postgres FTS + pg_trgm) |
| [004](docs/decisions/ADR-004-tanstack-query.md) | TanStack Query v5 (por causa do offline) |
| [005](docs/decisions/ADR-005-oauth-only.md) | Só OAuth, sem senha |
| [006](docs/decisions/ADR-006-append-only-results.md) | Resultados append-only (ISO/IEC 17025) |
| [007](docs/decisions/ADR-007-uuidv7-rls.md) | UUIDv7 + RLS com `SET LOCAL` |
| [008](docs/decisions/ADR-008-nf-core-ampliseq.md) | nf-core/ampliseq para FASTQ→ASV |
| [009](docs/decisions/ADR-009-vertical-slices.md) | Fatias verticais, não 8 fases horizontais |
| [010](docs/decisions/ADR-010-docker-compose-not-k3s.md) | Docker Compose até doer; k3s adiado |
| [012](docs/decisions/ADR-012-oauth-provider-adapter.md) | Provedor OAuth por trás de um adapter — Google isolado atrás de `OAuthProvider` |

O documento completo: **`RIZOMA_arquitetura_v2.md`**.
