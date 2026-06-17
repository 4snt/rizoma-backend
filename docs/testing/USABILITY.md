# Testes de Usabilidade — Rizoma

Avaliam facilidade de uso, intuição e experiência ao navegar pela interface.
Combina **teste com usuários** (tarefas cronometradas) e **avaliação heurística**
(10 heurísticas de Nielsen).

---

## 1. Teste com usuários (moderado)

**Participantes:** 3–5 pesquisadores `@ufvjm.edu.br` (Nielsen: 5 já revelam ~85% dos problemas).
**Método:** think-aloud — o participante narra o que pensa enquanto executa as tarefas, sem ajuda.

### Tarefas
| # | Tarefa | Métrica de sucesso | Tempo alvo |
|---|--------|--------------------|-----------|
| T1 | Criar um projeto 16S chamado "Solo Teste" | concluiu sem ajuda | < 60s |
| T2 | Subir uma pasta de FASTQs | pares detectados corretos | < 90s |
| T3 | Ajustar truncagem e rodar o DADA2 | identificou a aba DADA2 e o botão | < 120s |
| T4 | Exportar a tabela em Excel | baixou o arquivo certo | < 45s |
| T5 | Encontrar o status/progresso da análise | localizou barra/etapa | < 30s |

### Coleta por tarefa
- Sucesso (☐ total ☐ parcial ☐ falha) · Tempo real · Nº de erros · Hesitações/comentários.

### Pós-teste (SUS — System Usability Scale, 0–100)
Aplicar o questionário SUS de 10 itens. Meta: **SUS ≥ 70** (acima da média).

---

## 2. Avaliação heurística (Nielsen) — telas principais

Telas: Login · Metagenômica (abas Projeto/DADA2/Gráficos) · Lista de projetos.

| # | Heurística | Status atual / observação |
|---|------------|---------------------------|
| 1 | Visibilidade do status do sistema | ✅ barra de progresso por etapa + status do worker na sidebar |
| 2 | Correspondência com o mundo real | ✅ termos do domínio (ASV, marcador, taxonomia); revisar siglas |
| 3 | Controle e liberdade do usuário | ⚠ confirmar que ações destrutivas (🗑) pedem confirmação — OK |
| 4 | Consistência e padrões | ✅ componentes/estilos reutilizados (cards, badges) |
| 5 | Prevenção de erros | ✅ checklist de prontidão bloqueia DADA2 incompleto |
| 6 | Reconhecer em vez de lembrar | ✅ parâmetros pré-preenchidos com defaults por marcador |
| 7 | Flexibilidade e eficiência | ⚠ atalhos/seleção em lote para usuários avançados (futuro) |
| 8 | Estética e design minimalista | ✅ layout enxuto por abas |
| 9 | Ajudar a reconhecer/recuperar de erros | ✅ painel de erro do job mostra a mensagem; melhorar linguagem amigável |
| 10 | Ajuda e documentação | ⚠ adicionar tooltips/onboarding na primeira visita (futuro) |

**Classificação de severidade** (0 cosmético → 4 catastrófico) para cada achado,
com responsável e correção proposta.

---

## Registro

| Item | Data | Avaliador | Severidade | Ação |
|------|------|-----------|------------|------|
| | | | | |
