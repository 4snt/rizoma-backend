# Migrations legadas (OBSOLETAS — não aplique)

Estes `.sql` viviam em `api/app/migrations/` e eram aplicados em ordem alfabética
por um runner caseiro no startup da API. **Não são mais usados.** O schema agora
pertence ao Alembic (`api/alembic/`), consolidado em `0001_mvp_baseline.py`.

Estão aqui só como histórico — para responder "por que a tabela X é assim?".

Dois motivos concretos para a aposentadoria ([ADR-002](../decisions/ADR-002-alembic.md)):

- **`004_auth.sql` e `004_project_analyses.sql` têm o mesmo número.** A ordem entre
  eles era acidente alfabético ("a" < "p"), não decisão.
- **`005_large_objects.sql`** levou os FASTQ para dentro do Postgres como Large
  Objects, e **`008_drop_old_s3_keys.sql`** apagou o caminho de volta. Os dois foram
  revertidos pela [ADR-001](../decisions/ADR-001-object-storage.md).
