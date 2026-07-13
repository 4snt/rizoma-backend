# ADR-003 — Elasticsearch fora do MVP; busca em Postgres (FTS + pg_trgm)

Status: aceita
Data: 2026-07-13

## Contexto

O Compose subia um Elasticsearch 8.13 e o R Worker indexava resultados nele em
lotes de mil. A pergunta que ninguém tinha feito: **o que o ES faz aqui que o
Postgres não faz?**

| Necessidade real | Postgres resolve? |
|---|---|
| Buscar gene/táxon por nome | sim — `pg_trgm` + índice GIN |
| Busca textual em anotações | sim — `tsvector` + FTS |
| Agregar abundância | sim, e melhor: é SQL |
| Filtrar JSONB de resultados | sim — índice GIN em JSONB |
| Full-text em milhões de docs, facetado, fuzzy, com scoring | não — aí sim ES |

O projeto não está no último caso, e não vai estar no horizonte do MVP.

Enquanto isso, o ES custa: um serviço stateful inteiro para operar, fazer backup,
monitorar e manter sincronizado com o Postgres (dual-write, com todas as janelas
de inconsistência que isso implica). Para um desenvolvedor solo, esse custo é
medido em semanas.

## Decisão

Remover o Elasticsearch do Compose, do `requirements.txt` e do MVP. A busca passa
a ser Postgres: FTS (`tsvector`) para texto, `pg_trgm` + GIN para nome
aproximado, GIN em JSONB para os resultados.

A interface de busca continua atrás da Anti-Corruption Layer, então reintroduzir
o ES depois é implementar um adapter — não reescrever chamadas espalhadas.

**Gatilho de reversão, explícito:** quando a busca em Postgres passar de ~300 ms
num dataset real de produção. Antes disso, não.

## Alternativas

- **Manter o ES "já que está funcionando".** Descartada: está funcionando num
  banco de teste. O custo é operacional e aparece depois.
- **Trocar por OpenSearch/Meilisearch/Typesense.** Descartadas: resolvem o mesmo
  problema que não temos, e continuam sendo um segundo datastore para sincronizar.

## Consequências

Fica mais fácil: um serviço a menos no Compose, no backup e no monitoramento;
fim do dual-write e da divergência entre índice e banco; a busca passa a ser
transacional — o que foi commitado está buscável.

Fica mais difícil: busca fuzzy e ranking sofisticados dão mais trabalho em
Postgres; se o volume crescer muito, será preciso ajustar índices GIN e
possivelmente voltar atrás — e por isso o gatilho acima está escrito.
