# ADR-008 — nf-core/ampliseq para FASTQ→ASV; o R Worker fica com a estatística

Status: aceita
Data: 2026-07-13

## Contexto

O pipeline de FASTQ até tabela de ASV foi escrito à mão, chamando DADA2 direto do
R Worker: filtro e trim, aprendizado de erro, denoise, merge, remoção de quimera,
atribuição taxonômica contra SILVA/UNITE. Cada uma dessas etapas tem parâmetros
que precisam ser certos, e "certo" varia entre 16S e ITS.

Isso é reimplementar, com um autor e sem revisão, um pipeline que já existe
validado, versionado e mantido por uma comunidade: o `nf-core/ampliseq`. Ele faz
16S e ITS, roda o mesmo DADA2 por baixo, e entrega a rastreabilidade que a v1 quer
(versões de ferramenta, checksums, relatório MultiQC) de graça.

Um TCC de bioinformática é avaliado pela análise, não por ter reescrito o
preprocessamento.

## Decisão

`nf-core/ampliseq` (Nextflow) é o dono do trecho **FASTQ → tabela de ASV +
taxonomia**. O R Worker deixa de fazer DADA2 e passa a fazer só o que é
específico do Rizoma: a estatística e a ecologia — ANCOM-BC2, MaAsLin2, DESeq2,
SpiecEasi, phyloseq, vegan, e as PCoAs.

A fronteira entre os dois é o artefato: o ampliseq escreve a tabela de ASV e a
taxonomia no object storage; o R Worker lê de lá e monta o phyloseq.

## Alternativas

- **Manter o DADA2 à mão.** Descartada: é manter um pipeline crítico sem revisão
  externa, e gastar meses no problema que não é o do projeto.
- **QIIME2 como pipeline principal.** Descartada: o `QiimeAdapter` continua
  existindo na ACL, mas o QIIME2 impõe seu próprio formato de artefato e sua
  própria CLI; o ampliseq entrega o mesmo resultado com melhor integração a
  containers e retomada de execução.
- **Snakemake/WDL.** Descartadas: o Nextflow é o que o nf-core usa, e o valor
  está no catálogo do nf-core, não no motor.

## Consequências

Fica mais fácil: o preprocessamento passa a ser validado pela comunidade e
citável no TCC; retomada de execução (`-resume`), paralelismo e relatório de
versões vêm prontos; o R Worker encolhe e fica com o que interessa.

Fica mais difícil: entra o Nextflow como runtime novo (mais uma coisa para
instalar e operar); o job deixa de ser uma chamada de função e vira um processo
externo com exit code, o que muda o modelo de execução do worker; e o pipeline
passa a ser uma caixa que precisa ser configurada por arquivo de parâmetros, não
por código — customização fina fica menos direta.
