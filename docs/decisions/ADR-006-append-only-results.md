# ADR-006 — Resultados e laudos são append-only e versionados

Status: aceita
Data: 2026-07-13

## Contexto

A v1 dizia que "a auditoria registra valor anterior e novo" — isto é, o resultado
é atualizado no lugar e a trilha fica numa tabela paralela de auditoria.

Isso não sobrevive à ISO/IEC 17025. A norma exige rastreabilidade do resultado:
qual método, qual versão do método, qual analista, qual instrumento, quando, e
o que foi emitido ao cliente. Um `UPDATE` na linha do resultado destrói o objeto
que a norma quer rastrear e deixa como prova apenas um log que a própria
aplicação escreveu — e que a própria aplicação poderia não ter escrito.

Se um laudo já foi emitido e o valor muda, o que aconteceu não é "o valor mudou".
É: **um novo resultado foi produzido, e o laudo anterior foi retificado.** Os dois
existem. O cliente tem uma cópia do antigo.

## Decisão

Resultado e laudo são **imutáveis**. Nunca há `UPDATE` no valor: correção gera
uma **nova versão**, encadeada à anterior (`supersedes_id`), com motivo da
retificação. A versão vigente é derivada (a mais recente não superada), não um
campo mutável.

Isso vale para `analysis_results` e para o laudo em PDF, que carrega número de
versão e QR de verificação — o PDF antigo, que está no email do cliente, continua
verificável, e a verificação informa que existe versão mais nova.

Reforço no banco, não só na aplicação: privilégio de `UPDATE`/`DELETE` negado ao
papel de runtime nessas tabelas.

## Alternativas

- **UPDATE + tabela de auditoria (a v1).** Descartada: a auditoria é escrita pelo
  mesmo código que faz o update; se ele tiver um bug ou for burlado, não sobra
  prova. E não atende 17025.
- **Soft delete (`deleted_at`).** Descartada: resolve o apagar, não o corrigir, e
  ainda permite `UPDATE` no valor.
- **Event sourcing no sistema inteiro.** Descartada como default: é a modelagem
  certa para cadeia de custódia (§5.6) e exagerada para o resto do CRUD.

## Consequências

Fica mais fácil: a resposta a "por que este número mudou?" existe e é auditável;
a conformidade com 17025 deixa de ser retrofit; reprocessar uma análise nunca
apaga o resultado que embasou uma decisão passada.

Fica mais difícil: toda query de leitura precisa filtrar pela versão vigente (e
esquecer esse filtro é um bug silencioso — vale uma view); a tabela cresce
monotonicamente; corrigir um typo custa uma versão nova, o que é chato e é
exatamente o ponto.
