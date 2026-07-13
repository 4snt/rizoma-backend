# R Worker — pendente de religação à arquitetura v2

**Estado: NÃO religado.** O R Worker ainda fala com a arquitetura anterior e
**vai quebrar se subir com `make up-worker`**. Por isso ele está num profile
separado do Compose (`--profile worker`) e não sobe no `make up` padrão.

Os endpoints que o worker precisa consumir **já existem e estão testados**:
`POST /api/v2/jobs/worker/dequeue`, `/heartbeat`, `/complete`, `/fail`
(autenticação por header `X-Worker-Token`). O que falta é o worker passar a
usá-los em vez de falar direto com o banco.

## O que está desalinhado

| Ponto | Hoje (v1) | Precisa virar (v2) |
|-------|-----------|--------------------|
| Conexão ao banco | `dbConnect` direto, papel `r_worker`, db `bioinformatica` | não conectar direto; consumir os endpoints `/worker/*` via HTTP |
| Fila | `LISTEN new_job` + `SELECT ... FOR UPDATE` na mão | `POST /worker/dequeue` (o backend já faz o SKIP LOCKED) |
| Entrada (FASTQ/phyloseq) | Large Object OID lido do Postgres | baixar da URL assinada interna que vem em `payload.input_files` |
| Elasticsearch (`es_helpers.R`) | indexa resultados no ES | **removido** (ADR-003). Resultado vai no `POST /worker/complete` |
| `organization_id` | inexistente no schema antigo | todo resultado pertence a uma org; vem no job do dequeue |

## Recomendação (do plano v2, ADR-008)

Separar as duas responsabilidades que hoje estão juntas no R Worker:

1. **FASTQ → tabela de ASV**: delegar ao `nf-core/ampliseq` (Nextflow,
   validado pela comunidade). Sai o `dada2_silva.R` escrito à mão.
2. **Estatística** (ANCOM-BC2, MaAsLin2, DESeq2, SpiecEasi): continua no R —
   é o diferencial científico. Passa a receber o phyloseq por URL assinada e a
   devolver JSON pelo endpoint `/worker/complete`.

Isto é uma fatia de trabalho própria, não um ajuste de configuração. Um
meio-conserto (só trocar o nome do papel/banco) deixaria o worker "subindo" mas
falhando ao tentar ler um Large Object que não existe mais — pior que a falha
honesta atual.
