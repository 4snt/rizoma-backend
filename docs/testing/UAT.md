# Testes de Aceitação do Usuário (UAT) — Rizoma

Validação pelos usuários finais (pesquisadores e admin) de que o sistema atende
às necessidades reais antes de produção. Cada roteiro tem **passos** e
**critérios de aceite** (✅ = passou).

> Ambiente: app no ar (`rizoma.flipafile.com` ou local), conta `@ufvjm.edu.br`.

---

## Persona A — Pesquisador

### UAT-01 — Cadastrar um projeto
**Passos:** Menu *Metagenômica* → aba *Projeto* → ⊕ Novo Projeto → preencher
código, nome, marcador (16S/ITS), marcar análises → *Criar Projeto*.
**Aceite:**
- ✅ Projeto aparece na lista da esquerda com o código e o badge do marcador.
- ✅ Não há campo BioProject no formulário.
- ✅ Criação funciona sem ser admin (qualquer usuário logado).

### UAT-02 — Carregar FASTQs
**Passos:** Projeto selecionado → aba *Projeto* → ① Amostras → *Upload FASTQ* →
modo *Pasta* → selecionar a pasta → *Enviar pares*.
**Aceite:**
- ✅ Pares R1/R2 detectados automaticamente e listados com ✓.
- ✅ Após envio, as amostras aparecem na tabela com grupo/réplica.

### UAT-03 — Rodar o DADA2 e acompanhar progresso
**Passos:** aba *DADA2* → revisar parâmetros → *Salvar parâmetros* →
checklist 4/4 verde → *Rodar DADA2*.
**Aceite:**
- ✅ Botão só habilita com a checklist completa.
- ✅ Barra de progresso avança por etapa (filtragem → … → tabela) com % real.
- ✅ Em caso de falha, o painel de erro mostra a mensagem do worker.

### UAT-04 — Ver e exportar a tabela de ASVs
**Passos:** aba *Gráficos* → tabela de abundância → trocar nível taxonômico →
*⬇ Excel* / *⬇ CSV completo*.
**Aceite:**
- ✅ Tabela popula após a análise metagenômica.
- ✅ Export Excel abre no LibreOffice/Excel com todos os níveis + abundância relativa.

---

## Persona B — Administrador

### UAT-05 — Excluir projeto de teste
**Passos:** lista de projetos → 🗑 no projeto → confirmar.
**Aceite:**
- ✅ Admin (ou criador) vê o ícone 🗑.
- ✅ Projeto e seus dados somem da lista após confirmação.

### UAT-06 — Gerenciar convites/usuários
**Passos:** menu *Usuários* → criar convite → alterar role.
**Aceite:**
- ✅ Apenas admin acessa `/admin/users`.
- ✅ Convite criado aparece na lista.

---

## Registro de execução

| ID | Data | Testador | Resultado | Observações |
|----|------|----------|-----------|-------------|
| UAT-01 | | | ☐ Passou ☐ Falhou | |
| UAT-02 | | | ☐ Passou ☐ Falhou | |
| UAT-03 | | | ☐ Passou ☐ Falhou | |
| UAT-04 | | | ☐ Passou ☐ Falhou | |
| UAT-05 | | | ☐ Passou ☐ Falhou | |
| UAT-06 | | | ☐ Passou ☐ Falhou | |
