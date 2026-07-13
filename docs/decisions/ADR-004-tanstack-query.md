# ADR-004 — TanStack Query v5 no lugar do SWR

Status: aceita
Data: 2026-07-13

## Contexto

A v1 da arquitetura escrevia "SWR **ou** TanStack Query — pode ser mantido, desde
que usado de forma consistente". Isso não é flexibilidade, é adiar a decisão.

O requisito que desempata não é preferência de API: é o **trabalho de campo**. A
coleta acontece offline, e o app precisa aceitar escrita sem rede, guardar a
mutação e reenviá-la quando a conexão voltar — uma fila de mutações (outbox), com
retry, deduplicação por idempotency key e ordem preservada.

O SWR resolve muito bem cache e revalidação de **leitura**. Ele não tem fila de
mutações offline. Construir uma por cima dele é reimplementar o que o TanStack
Query já entrega.

## Decisão

TanStack Query v5 em todo o frontend, com persistência do cache em IndexedDB e
`persistQueryClient` + mutações com `mutationFn` retomáveis para o outbox.

## Alternativas

- **SWR + outbox caseiro.** Descartada: é escrever e manter a parte mais difícil
  do sistema à mão.
- **RTK Query.** Descartada: traz o Redux junto, e não há estado global que o
  justifique.
- **Replicache / ElectricSQL / PowerSync (sync engines de verdade).** Adiadas:
  resolvem o problema melhor, mas são uma mudança de paradigma e um serviço a
  mais. Reconsiderar se o conflito de escrita concorrente virar dor real.

## Consequências

Fica mais fácil: offline em campo (§6 da arquitetura) tem base pronta;
invalidação declarativa; devtools decentes.

Fica mais difícil: migrar as telas que já usam SWR (`useSWR` → `useQuery`); a
curva de aprendizado é maior; e o cache persistido precisa de política de versão
— um schema de dado velho no IndexedDB de um celular que ficou um mês offline é
um problema real, não hipotético.
