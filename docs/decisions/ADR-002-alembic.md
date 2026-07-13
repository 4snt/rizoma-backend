# ADR-002 — Alembic desde já, no lugar do runner de migrations caseiro

Status: aceita
Data: 2026-07-13

## Contexto

O repositório tinha um runner próprio (`app/core/migrations.py`) que aplicava os
`.sql` de `app/migrations/` em ordem alfabética, no startup da API. O diretório
continha:

```
004_auth.sql
004_project_analyses.sql     <- DOIS arquivos com o número 004
```

`004_auth.sql` roda antes de `004_project_analyses.sql` **por acaso**, porque
"a" < "p". Não há ordem determinística, não há registro do que foi aplicado num
banco, não há rollback, e nada impede que o próximo commit crie um terceiro 004.

Com 40 tabelas multi-tenant e RLS, consertar isso retroativamente é impraticável.

## Decisão

Alembic, agora — não "temporariamente". As nove migrations antigas foram
consolidadas numa baseline única (`alembic/versions/0001_mvp_baseline.py`) e os
`.sql` originais foram movidos para `docs/legacy-migrations/`, como histórico.

O Alembic roda com **driver síncrono (`psycopg`)** e com o papel **dono do
schema** (`api_user`), não com o papel de runtime. asyncpg não serve para
migration: ele executa tudo como prepared statement, e prepared statement recusa
múltiplos comandos num mesmo `execute` — migration é DDL em bloco. Daí as duas
DSNs em `Settings`: `postgres_dsn` (asyncpg, runtime) e `migration_dsn`
(psycopg, DDL).

A migration roda no start do container da API
(`alembic upgrade head && uvicorn ...`), antes do servidor subir.

## Alternativas

- **Manter o runner caseiro "por enquanto".** Descartada: "temporário" é como se
  chama a dívida que ninguém paga. O bug dos dois 004 já existe.
- **Consertar o runner (numeração, tabela de controle, lock).** Descartada:
  seria reescrever o Alembic, pior e sem comunidade.
- **sqlx/dbmate/Flyway.** Descartadas: são mais uma ferramenta e mais um runtime
  no projeto; o Alembic já fala SQLAlchemy, que é o ORM em uso.

## Consequências

Fica mais fácil: ordem determinística por cadeia de revisões; `alembic
downgrade`; autogenerate a partir dos modelos; saber exatamente em que versão um
banco está.

Fica mais difícil: autogenerate não enxerga tudo (RLS policies, roles, extensões,
triggers precisam de `op.execute` escrito à mão); a baseline precisa ser marcada
com `alembic stamp` em qualquer banco que já tenha as tabelas antigas, senão o
upgrade tenta recriá-las.
