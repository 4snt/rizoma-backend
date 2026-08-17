# ADR-011 — Pesquisador (Customer) fundido em User

Status: aceita
Data: 2026-08-17

## Contexto

O LIMS tinha duas tabelas de pessoa que não se falavam: `customers`
(nome, e-mail de contato, documento, telefone — um contato solto, sem
login) e `users`/`organization_members` (conta Google, papel real,
membro de uma organização). No frontend isso virou dois menus
parecidos e confusos: "Pesquisadores" (`/customers`, edita a tabela
solta) e "Usuários" (`/admin/users`, gerencia quem loga de verdade).

Na prática do laboratório, todo pesquisador que interage com o sistema
— mesmo só pra receber um laudo — é sempre alguém com e-mail
institucional (`@ufvjm.edu.br`) e conta Google. A tabela `customers`
nunca correspondeu a uma pessoa real fora do sistema: era um cadastro
duplicado, sem vínculo, que podia divergir do nome/e-mail reais do
usuário correspondente.

## Decisão

`customers` deixa de existir como conceito próprio. `projects.customer_id`
(FK pra `customers`) vira `projects.customer_user_id` (FK pra `users`).
O "pesquisador" de um projeto é sempre um `organization_member` — a
mesma pessoa que loga, com o mesmo papel (`org_admin`, `coordinator`,
`client`, etc. — ver `app/shared/context.py::PERMISSIONS`).

Consequências diretas no código:

- Não existe mais `POST /api/v2/lims/customers`. Criar um "pesquisador"
  novo é convidar um usuário (`POST /api/v2/identity/invitations`) — o
  mesmo fluxo de convidar qualquer membro da organização.
- `POST /api/v2/lims/projects` valida que `customer_user_id`, se
  informado, já é membro da organização (`customer_is_member`,
  `PgProjectRepository`) — não cria a pessoa, só referencia quem já
  existe.
- O laudo (`reports/snapshot.py`) lê nome e e-mail de `users` em vez de
  `customers`; os campos `document`/`contact_phone` (que só existiam na
  tabela solta) somem do laudo.
- No frontend, o menu "Pesquisadores" deixa de existir separado —
  gerenciar pesquisador é gerenciar usuário (tela de Usuários), e
  escolher o pesquisador de um projeto é escolher um membro existente.

Migration `0007_customer_to_user`: adiciona `customer_user_id`, faz
backfill por e-mail (`customers.contact_email` = `users.email`, mesma
organização) e derruba `projects.customer_id`. A tabela `customers` em
si não é apagada nesta migration — fica como histórico morto até
confirmar que nenhum dado real dependia só dela.

## Alternativas

- **Customer com vínculo opcional pra User.** Considerada e descartada
  pelo usuário: mantém dois cadastros de pessoa a sincronizar, e a
  maioria dos "clientes externos sem login" nunca existiu de verdade
  neste laboratório específico — todo mundo que usa o Rizoma tem conta
  institucional.
- **Manter os dois, só unificar a navegação.** Descartada: resolveria
  a confusão de menu sem resolver a causa (dois cadastros de pessoa
  divergentes).

## Consequências

Fica mais fácil: um cadastro de pessoa só, sem risco de nome/e-mail
divergente entre "cliente" e "usuário" da mesma pessoa; convidar
pesquisador novo é o mesmo fluxo de convidar qualquer membro; o menu do
frontend perde uma tela inteira duplicada.

Fica mais difícil: um projeto não pode mais ter "cliente" que nunca vai
logar no sistema (ex.: uma pessoa jurídica externa sem e-mail
institucional) — se isso aparecer como necessidade real, é um caso novo
a desenhar (provavelmente um papel `client` com convite restrito, não a
volta da tabela solta). Dados antigos de `customers` sem e-mail que bata
com nenhum usuário ficam com `customer_user_id` nulo até alguém revisar
manualmente.
