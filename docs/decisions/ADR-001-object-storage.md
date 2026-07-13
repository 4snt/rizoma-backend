# ADR-001 — MinIO + presigned URL: sair dos PostgreSQL Large Objects

Status: aceita
Data: 2026-07-13

## Contexto

A migration `005_large_objects.sql` levou os FASTQ para dentro do banco:

```sql
ALTER TABLE samples ADD COLUMN fastq_r1_oid OID;
ALTER TABLE pipeline_jobs ADD COLUMN phyloseq_oid OID;
```

e a `008_drop_old_s3_keys.sql` apagou o caminho de volta, derrubando as colunas
de chave S3. Ou seja: hoje os arquivos vivem em `pg_largeobject`.

Um FASTQ tem 1–10 GB por amostra. Cem amostras são ~500 GB dentro do Postgres.
Os problemas não são teóricos:

- todo Large Object passa pelo WAL, então backup e replicação crescem na mesma
  proporção;
- `pg_dump` serializa os LOs — um dump de 2 minutos vira horas;
- LO não tem streaming HTTP: a API precisa ler o arquivo inteiro para servir;
- não há upload direto do browser — cada byte atravessa a API, que morre de
  memória.

Isso funciona no notebook com três amostras de teste e falha no primeiro projeto
real.

## Decisão

Object storage S3-compatível (MinIO em dev e em produção), com **upload e
download diretos do browser por URL assinada**. O Postgres guarda só o catálogo
de metadados: chave do objeto, tamanho, SHA-256, content-type.

A API **nunca toca o corpo do arquivo** — ela assina a URL e sai do caminho.

Consequência operacional imediata: existem dois endpoints S3. O interno
(`S3_ENDPOINT`, `http://minio:9000`), que a API usa para falar com o MinIO, e o
público (`S3_PUBLIC_ENDPOINT`, `http://localhost:9000`), que é o host embutido na
assinatura. Como a assinatura V4 cobre o header `Host`, assinar com o host
interno e acessar pelo externo devolve 403.

O R Worker também baixa por presigned URL (`httr::GET`), em vez de puxar o
arquivo para dentro do banco.

## Alternativas

- **Manter os Large Objects.** Descartada: os quatro problemas acima não têm
  mitigação, só adiamento.
- **Arquivos no filesystem da VM.** Descartada: não dá réplica, não dá URL
  assinada, e amarra o worker à mesma máquina da API.
- **S3 gerenciado (AWS/R2) já no MVP.** Adiada: MinIO fala o mesmo protocolo, então
  a troca depois é de credencial e endpoint, não de código.

## Consequências

Fica mais fácil: backup do Postgres volta a ser rápido; upload de 10 GB não
consome memória da API; o storage escala sem tocar no banco; trocar MinIO por S3
de verdade é mudar variável de ambiente.

Fica mais difícil: são dois sistemas para manter consistentes — um objeto órfão
no bucket ou uma linha apontando para um objeto que não existe agora são estados
possíveis, e precisam de reconciliação. O bucket precisa ser criado no bootstrap
(serviço `minio-init` no Compose). E é preciso uma migration de saída dos LOs
para os dados que já estão lá.
