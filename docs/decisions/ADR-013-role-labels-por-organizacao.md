# ADR-013 — Rótulo de papel customizável por organização

Status: aceita
Data: 2026-08-17

## Contexto

Os 8 papéis técnicos (`org_admin`, `coordinator`, `tech_responsible`,
`field_tech`, `lab_tech`, `bioinformatician`, `client`, `viewer`) decidem
permissão de verdade — RLS, `ctx.require()`, tudo em cima dessas 8 strings
fixas (`app/shared/context.py::PERMISSIONS`).

Mas o **nome** que um laboratório usa pra cada papel é institucional, não
técnico. O NEBIM pode organizar por titulação (Graduando, Mestrando,
Doutorando); outro laboratório que rode sua própria instância do Rizoma
(é GPL-3.0) pode organizar por função (Estagiário, Técnico, Pesquisador
Sênior) ou qualquer outro critério. Embutir um vocabulário fixo no código
(como o `ROLE_LABEL` hardcoded que existia em `app/admin/members/page.tsx`)
funciona pra um laboratório e é errado pra todos os outros.

## Decisão

`organizations.role_labels` é um JSONB simples: `{papel_técnico: rótulo}`.
Só `org_admin` pode escrever (`PUT /api/v2/identity/organizations/role-labels`,
substitui o mapa inteiro — não é PATCH incremental, o cliente lê o estado
atual e reenvia completo). Papel sem entrada no mapa cai no rótulo padrão
em português que já existia — a organização só sobrescreve o que quiser,
nunca precisa mapear os 8 de uma vez.

O papel técnico em si nunca muda de nome no banco nem no JWT — só o rótulo
exibido muda. `MemberOut.role` e `InvitationOut.role` continuam devolvendo
a string técnica (`lab_tech`); é o frontend que resolve
`role_labels[role] ?? DEFAULT_ROLE_LABEL[role] ?? role` no momento de
exibir, num único lugar (`lib/role-labels.ts`), nunca hardcoded em cada
tela que mostra um papel.

## Alternativas

- **Papéis customizados de verdade por organização** (não só rótulo —
  permissões próprias). Descartada nesta rodada: a organização decidiu
  que o problema real hoje é só nomenclatura, não um conjunto de
  permissões diferente do que os 8 papéis já cobrem. Se aparecer essa
  necessidade depois, é uma ADR nova — provavelmente uma tabela de
  permissões customizadas por org, não um JSONB de rótulo.
- **Rótulo por usuário, não por organização.** Descartada: o rótulo é do
  papel dentro daquele laboratório (todo `lab_tech` da mesma org chama-se
  igual), não uma preferência individual.

## Consequências

Fica mais fácil: qualquer laboratório que adote o Rizoma usa seu próprio
vocabulário sem fork nem mudança de código; o frontend nunca mais hardcoda
rótulo de papel em mais de um lugar.

Fica mais difícil: telas que mostram papel de usuários de **mais de uma
organização ao mesmo tempo** (nenhuma existe hoje) precisariam resolver o
rótulo por org de cada linha, não um mapa único global.
