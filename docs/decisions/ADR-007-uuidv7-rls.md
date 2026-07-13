# ADR-007 — UUIDv7, `organization_id` universal e RLS com `SET LOCAL`

Status: aceita
Data: 2026-07-13

## Contexto

Três problemas que se resolvem juntos.

**1. Chave primária.** O app de campo escreve offline: o cliente precisa gerar o
ID da amostra sem falar com o servidor, senão não há coleta sem rede. Isso elimina
`serial`/`bigserial`. Mas UUIDv4 é aleatório, e chave aleatória em índice B-tree
espalha a escrita por todas as páginas — o índice fragmenta e o cache não ajuda.

**2. Multi-tenant.** O Rizoma vai atender mais de uma organização. Filtrar por
`organization_id` no `WHERE` de cada query funciona até a query que alguém
esqueceu de filtrar — e essa query vaza dado de um cliente para outro.

**3. A armadilha do pool.** RLS depende de um parâmetro de sessão com a org
corrente. Com pool de conexões, `SET` (sem `LOCAL`) persiste na conexão depois
que a requisição termina: a próxima requisição pega a conexão reciclada com o
`organization_id` da requisição anterior, de outra organização. É um vazamento
cross-tenant silencioso e não determinístico.

## Decisão

**UUIDv7** como PK em todas as tabelas. É UUID (gerável no cliente, offline) mas
com prefixo temporal, então é monotonicamente crescente e se comporta como chave
sequencial no índice.

**`organization_id` em toda tabela**, sem exceção — inclusive nas que "obviamente
pertencem" a outra via FK. Sem a coluna local, a policy precisaria de JOIN, e
policy com JOIN é lenta e fácil de errar.

**RLS ligada em toda tabela**, com a policy comparando `organization_id` ao
parâmetro da transação, e o parâmetro definido com **`SET LOCAL`** — que vale
apenas até o fim da transação e some quando a conexão volta ao pool:

```python
# ERRADO — vaza entre requisições
await conn.execute("SET app.organization_id = $1", org)

# CERTO — SET LOCAL, dentro da transação
async with conn.transaction():
    await conn.execute("SELECT set_config('app.organization_id', $1, true)", org)
```

**Três papéis de banco**, e essa é a parte que não é decorativa:

| Papel | Atributos | Para quê |
|---|---|---|
| `api_user` | dono do schema, superusuário em dev | rodar as migrations |
| `rizoma_app` | **NOSUPERUSER NOBYPASSRLS** | runtime da API |
| `rizoma_system` | **BYPASSRLS** | login, reaper de jobs, verificação pública de laudo |

`rizoma_app` **precisa** ser NOSUPERUSER: no Postgres, superusuário ignora RLS em
silêncio. A policy continua no catálogo, o teste passa, e o isolamento não existe.
Rodar a API como superusuário é ter RLS de enfeite.

E **não existe "GUC de bypass"** — a tentação de fazer
`SET app.bypass_rls = true` para o job de sistema é um buraco, porque qualquer
usuário conectado pode setar um GUC customizado. Bypass tem que ser **atributo de
papel**, que o usuário não pode conceder a si mesmo. Daí o `rizoma_system`.

Os papéis `rizoma_app` e `rizoma_system` são criados pela própria migration
baseline, para que o banco nunca exista sem eles.

Um teste de isolamento multi-tenant é obrigatório na suite.

## Alternativas

- **`bigserial` + filtro no WHERE.** Descartada: não permite ID offline, e o
  isolamento fica na disciplina de quem escreve a query.
- **UUIDv4.** Descartada: resolve o offline, custa a localidade do índice.
- **Um schema (ou um banco) por organização.** Descartada: migrar N schemas a
  cada deploy, e o número de orgs esperado não justifica.
- **`SET` sem `LOCAL` + reset manual no fim da requisição.** Descartada: funciona
  até a exceção que pula o reset.
- **GUC de bypass para os jobs de sistema.** Descartada — ver acima. É burlável
  pelo próprio papel que deveria ser contido.

## Consequências

Fica mais fácil: o isolamento passa a ser garantido pelo banco, não pela memória
do programador; a query esquecida não vaza, ela simplesmente não retorna nada;
o cliente gera IDs offline sem coordenação.

Fica mais difícil: todo acesso ao banco tem de passar pelo helper que abre
transação e faz o `SET LOCAL` (acesso fora dele retorna zero linhas, o que
confunde no começo — é o modo de falha *correto*, mas parece bug); há três
credenciais para gerenciar em vez de uma; `EXPLAIN` fica mais barulhento com as
policies; e o que for legitimamente cross-org precisa ser roteado
conscientemente pelo engine do `rizoma_system` — o que é bom, porque força a
decisão a ser explícita.
