# ADR-009 — Fatias verticais, não 8 fases horizontais

Status: aceita
Data: 2026-07-13

## Contexto

A v1 planejava 8 fases sequenciais, organizadas por camada: primeiro o modelo de
dados, depois a API, depois os pipelines, depois o frontend, depois relatórios,
depois qualidade. Cada fase entrega uma camada **completa** — e uma camada
completa não é utilizável por ninguém.

Nesse desenho, a primeira coisa que um usuário real consegue **fazer** aparece lá
pelo mês 30. Até lá não há feedback, e todo o risco de ter construído a coisa
errada permanece intacto e acumulado.

Pior: as decisões difíceis (offline, RLS, imutabilidade de resultado) ficam para
o fim, quando mudar de ideia custa reescrever tudo que veio antes.

## Decisão

**Walking skeleton** primeiro: um caminho fino que atravessa **todas** as camadas
e funciona ponta a ponta — login → criar projeto → subir FASTQ → rodar uma
análise → ver o gráfico. Feio, sem recurso, mas real e implantado.

Depois, **fatias verticais**, cada uma entregando uma capacidade completa e usável:

| Fase 0 | Dívida técnica bloqueante (MinIO, Alembic, sem ES, RLS) |
| Fatia 1 | Walking skeleton |
| Fatia 2 | Campo (offline/PWA) |
| Fatia 3 | Multi-organização + cliente |
| Fatia 4 | Qualidade (17025) |
| Fatia 5+ | Backlog — só sob demanda de usuário real |

A Fase 0 é a exceção que confirma a regra: é horizontal porque é dívida que
bloqueia qualquer fatia (não dá para construir a Fatia 1 em cima de FASTQ em
Large Object e migration não determinística).

## Alternativas

- **As 8 fases da v1.** Descartada: valor no mês 30, feedback zero até lá.
- **Ir direto para as fatias, sem a Fase 0.** Descartada: construir sobre os LOs
  e sobre o runner de migration quebrado significa refazer a fatia inteira depois.
- **Scrum com sprints por camada.** Descartada: é a mesma waterfall com nomes
  novos e uma cerimônia por semana.

## Consequências

Fica mais fácil: existe algo demonstrável e criticável cedo; o risco de construir
a coisa errada é descoberto em semanas, não em anos; cada fatia é um ponto de
parada honesto — se o TCC acabar na Fatia 2, o que existe funciona.

Fica mais difícil: exige dizer não a recurso fora da fatia atual (e a lista de
não-objetivos precisa ser mantida e defendida); algumas partes serão tocadas mais
de uma vez, o que parece retrabalho e é, na verdade, o preço de aprender antes de
generalizar; e a arquitetura precisa aguentar ser estendida de dentro para fora,
sem "a fase em que tudo é refatorado".
