#!/usr/bin/env Rscript
# tsv_to_phyloseq.R
#
# Converte tabelas TSV do laboratório (taxonomia + abundância relativa)
# em objetos phyloseq .rds prontos para análise estatística.
#
# Uso:
#   Rscript tsv_to_phyloseq.R <tsv_path> <output_rds> [project_code]
#
# Exemplo:
#   Rscript tsv_to_phyloseq.R tabelas/Zinia_couve_ITS_fungos.tsv \
#     /tmp/INOVAHERB_ITS.rds INOVAHERB
#
# Formato esperado do TSV:
#   Coluna 1 : ASV (hash)
#   Colunas 2-9 : Dominio, Filo, Classe, Ordem, Familia, Genero, Especie, Classificacao_final
#   Demais   : amostras (ex: A_01_T1B2, A_02_T1B2_B) com abundância relativa 0-1

suppressPackageStartupMessages({
  library(phyloseq)
})

TAX_COLS <- c("Dominio","Filo","Classe","Ordem","Familia","Genero","Especie","Classificacao_final")

# Extrai grupo de tratamento e réplica do nome da amostra
# Ex: A_01_T1B2 → T1B2 / A_02_T1B2_B → T1B2_B / A_51 → S51
parse_sample_name <- function(name) {
  m <- regmatches(name, regexpr("T\\d+B\\d+(?:_[AB])?", name, perl=TRUE))
  if (length(m) == 0) {
    # Sem grupo de tratamento: extrai número como ID de controle
    num <- regmatches(name, regexpr("\\d+$", name))
    group <- if (length(num) > 0) paste0("S", num) else "ctrl"
  } else {
    group <- m
  }
  b <- regmatches(group, regexpr("B(\\d+)", group))
  replicate <- if (length(b) > 0) as.integer(sub("B","",b)) else 1L
  list(treatment_group = group, replicate = replicate)
}

tsv_to_phyloseq <- function(tsv_path, project_code = "UNKNOWN") {
  message("Lendo: ", basename(tsv_path))
  df <- read.delim(tsv_path, sep="\t", check.names=FALSE, stringsAsFactors=FALSE)

  # Identifica colunas de amostras
  sample_cols <- setdiff(colnames(df), c("ASV", TAX_COLS))
  if (length(sample_cols) == 0) stop("Nenhuma coluna de amostra encontrada.")

  # --- OTU table ---
  # Abundância relativa × 10000 → pseudo-contagens (inteiro) para DESeq2/ANCOMBC
  # Preserva zeros como zeros
  otu_raw <- as.matrix(df[, sample_cols, drop=FALSE])
  mode(otu_raw) <- "numeric"
  otu_counts <- round(otu_raw * 10000)
  rownames(otu_counts) <- df$ASV
  OTU <- otu_table(otu_counts, taxa_are_rows=TRUE)

  # --- Taxonomy table ---
  tax_raw <- as.matrix(df[, intersect(TAX_COLS, colnames(df)), drop=FALSE])
  rownames(tax_raw) <- df$ASV
  colnames(tax_raw) <- c("Kingdom","Phylum","Class","Order","Family","Genus","Species","Label")[
    seq_len(ncol(tax_raw))
  ]
  tax_raw[tax_raw == "NA" | is.na(tax_raw)] <- "Unclassified"
  TAX <- tax_table(tax_raw)

  # --- Sample data ---
  parsed <- lapply(sample_cols, parse_sample_name)
  samp_df <- data.frame(
    sample_id       = sample_cols,
    treatment_group = sapply(parsed, `[[`, "treatment_group"),
    replicate       = sapply(parsed, `[[`, "replicate"),
    project_code    = project_code,
    row.names       = sample_cols,
    stringsAsFactors = FALSE
  )
  SAMP <- sample_data(samp_df)

  phyloseq(OTU, TAX, SAMP)
}

# --- Main ---
args <- commandArgs(trailingOnly=TRUE)
if (length(args) < 2) {
  cat("Uso: Rscript tsv_to_phyloseq.R <tsv> <output.rds> [project_code]\n")
  quit(status=1)
}

tsv_path    <- args[1]
output_rds  <- args[2]
project_code <- if (length(args) >= 3) args[3] else "UNKNOWN"

ps <- tsv_to_phyloseq(tsv_path, project_code)

message(sprintf(
  "phyloseq criado: %d ASVs × %d amostras | grupos: %s",
  ntaxa(ps), nsamples(ps),
  paste(sort(unique(sample_data(ps)$treatment_group)), collapse=", ")
))

saveRDS(ps, output_rds)
message("Salvo em: ", output_rds)
