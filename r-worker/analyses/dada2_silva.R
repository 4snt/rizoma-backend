library(dada2)
library(phyloseq)

# Parâmetros DADA2 conforme MarkerConfig em CLAUDE.md
.dada2_params <- function(marker_type) {
  if (marker_type == "16S") {
    list(
      trunc_len_f = 230L,
      trunc_len_r = 180L,
      ref_train   = "/refs/silva_nr99_v138.1_train_set.fa.gz",
      ref_species = "/refs/silva_species_v138.1.fa.gz",
      label       = "SILVA 138.1"
    )
  } else {                                 # ITS
    fasta <- .find_unite_fasta()
    list(
      trunc_len_f = 0L,                    # ITS: comprimento variável, sem truncagem
      trunc_len_r = 0L,
      ref_train   = fasta,
      ref_species = NULL,
      label       = "UNITE"
    )
  }
}

.find_unite_fasta <- function() {
  unite_dir <- "/refs/unite"
  if (!dir.exists(unite_dir)) {
    stop("Referência UNITE ausente em /refs/unite. ",
         "Reconstrua a imagem Docker após baixar o arquivo UNITE DADA2-formatted.")
  }
  fastas <- list.files(unite_dir,
    pattern = "\\.(fa|fasta|fa\\.gz|fasta\\.gz)$",
    full.names = TRUE, recursive = TRUE)
  if (length(fastas) == 0) stop("Nenhum FASTA UNITE encontrado em /refs/unite/")
  fastas[1]
}

run_dada2_silva <- function(payload, con) {
  job_id     <- payload$job_id
  project_id <- payload$project_id

  message(sprintf("[dada2] job=%s projeto=%s", job_id, project_id))

  # ── 1. Busca marker_type do projeto ───────────────────────────────────────
  proj <- DBI::dbGetQuery(con,
    sprintf("SELECT marker_type FROM projects WHERE id = '%s'", project_id))
  if (nrow(proj) == 0) stop("Projeto não encontrado: ", project_id)
  marker_type <- proj$marker_type[1]
  params <- .dada2_params(marker_type)

  message(sprintf("[dada2] Marcador: %s — Classificador: %s", marker_type, params$label))

  # ── 2. Busca amostras com FASTQs ──────────────────────────────────────────
  samples <- DBI::dbGetQuery(con, sprintf(
    "SELECT id, treatment_group, replicate, fastq_r1_oid, fastq_r2_oid
       FROM samples
      WHERE project_id = '%s'
        AND fastq_r1_oid IS NOT NULL
        AND fastq_r2_oid IS NOT NULL
      ORDER BY replicate, treatment_group",
    project_id
  ))
  if (nrow(samples) == 0) {
    stop("Nenhuma amostra com par FASTQ encontrada. Faça o upload dos arquivos primeiro.")
  }
  message(sprintf("[dada2] %d amostras encontradas", nrow(samples)))

  # ── 3. Download dos FASTQs para diretório temporário ─────────────────────
  tmpdir      <- file.path(tempdir(), paste0("dada2_", gsub("-", "", job_id)))
  filtered_d  <- file.path(tmpdir, "filtered")
  dir.create(filtered_d, recursive = TRUE, showWarnings = FALSE)

  smp_names <- make.names(
    paste0(samples$treatment_group, "_rep", samples$replicate),
    unique = TRUE
  )

  fnFs <- setNames(file.path(tmpdir, paste0(smp_names, "_R1.fastq.gz")), smp_names)
  fnRs <- setNames(file.path(tmpdir, paste0(smp_names, "_R2.fastq.gz")), smp_names)

  for (i in seq_len(nrow(samples))) {
    pg_download_binary(con, samples$fastq_r1_oid[i], fnFs[i])
    pg_download_binary(con, samples$fastq_r2_oid[i], fnRs[i])
    message(sprintf("[dada2] Download %d/%d: %s", i, nrow(samples), smp_names[i]))
  }

  # ── 4. Filter and Trim ────────────────────────────────────────────────────
  filtFs <- setNames(file.path(filtered_d, paste0(smp_names, "_F_filt.fastq.gz")), smp_names)
  filtRs <- setNames(file.path(filtered_d, paste0(smp_names, "_R_filt.fastq.gz")), smp_names)

  message("[dada2] filterAndTrim...")
  if (params$trunc_len_f > 0) {
    out <- dada2::filterAndTrim(
      fnFs, filtFs, fnRs, filtRs,
      truncLen  = c(params$trunc_len_f, params$trunc_len_r),
      maxN = 0, maxEE = c(2, 2), truncQ = 2, rm.phix = TRUE,
      compress = TRUE, multithread = TRUE
    )
  } else {
    # ITS: sem truncagem, usa minLen
    out <- dada2::filterAndTrim(
      fnFs, filtFs, fnRs, filtRs,
      maxN = 0, maxEE = c(2, 2), truncQ = 2, rm.phix = TRUE,
      minLen = 50,
      compress = TRUE, multithread = TRUE
    )
  }

  kept <- file.exists(filtFs) & file.exists(filtRs)
  if (!any(kept)) {
    stop("Todas as amostras foram removidas na filtragem. ",
         "Verifique a qualidade dos FASTQs e os parâmetros de truncagem.")
  }
  filtFs <- filtFs[kept]
  filtRs <- filtRs[kept]
  smp_filt <- smp_names[kept]
  n_removed <- sum(!kept)
  if (n_removed > 0) {
    message(sprintf("[dada2] %d amostra(s) removida(s) por qualidade insuficiente", n_removed))
  }
  message(sprintf("[dada2] Reads: entrada=%d saída=%d",
    sum(out[, 1], na.rm = TRUE), sum(out[, 2], na.rm = TRUE)))

  # ── 5. Error learning ─────────────────────────────────────────────────────
  message("[dada2] Aprendendo taxas de erro (forward)...")
  errF <- dada2::learnErrors(filtFs, multithread = TRUE)
  message("[dada2] Aprendendo taxas de erro (reverse)...")
  errR <- dada2::learnErrors(filtRs, multithread = TRUE)

  # ── 6. Denoising ──────────────────────────────────────────────────────────
  message("[dada2] Denoising...")
  dadaFs <- dada2::dada(filtFs, err = errF, multithread = TRUE)
  dadaRs <- dada2::dada(filtRs, err = errR, multithread = TRUE)

  # ── 7. Merge paired reads ─────────────────────────────────────────────────
  message("[dada2] Merging pares...")
  mergers <- dada2::mergePairs(dadaFs, filtFs, dadaRs, filtRs, verbose = FALSE)

  # ── 8. Sequence table + chimera removal ───────────────────────────────────
  seqtab <- dada2::makeSequenceTable(mergers)
  rownames(seqtab) <- smp_filt

  message("[dada2] Removendo quimeras...")
  seqtab_nc <- dada2::removeBimeraDenovo(seqtab, method = "consensus", multithread = TRUE)

  n_asvs <- ncol(seqtab_nc)
  message(sprintf("[dada2] ASVs finais: %d", n_asvs))
  if (n_asvs == 0) stop("Nenhuma ASV após remoção de quimeras.")

  # ── 9. Assign taxonomy ────────────────────────────────────────────────────
  message(sprintf("[dada2] Classificação taxonômica (%s)...", params$label))
  taxa <- dada2::assignTaxonomy(
    seqtab_nc, params$ref_train,
    multithread = TRUE, verbose = FALSE
  )
  if (!is.null(params$ref_species) && file.exists(params$ref_species)) {
    taxa <- dada2::addSpecies(taxa, params$ref_species)
    message("[dada2] Species assignment concluído")
  }

  # ── 10. Build phyloseq ────────────────────────────────────────────────────
  message("[dada2] Construindo phyloseq...")
  sample_idx <- match(smp_filt, smp_names)
  meta_df <- data.frame(
    sample_id       = as.character(samples$id[sample_idx]),
    treatment_group = samples$treatment_group[sample_idx],
    replicate       = samples$replicate[sample_idx],
    row.names       = smp_filt,
    stringsAsFactors = FALSE
  )

  ps <- phyloseq::phyloseq(
    phyloseq::otu_table(seqtab_nc, taxa_are_rows = FALSE),
    phyloseq::sample_data(meta_df),
    phyloseq::tax_table(taxa)
  )

  # ── 11. Save phyloseq LO + update job ────────────────────────────────────
  message("[dada2] Armazenando phyloseq no banco...")
  oid <- pg_upload_rds(con, ps)

  DBI::dbExecute(con,
    sprintf("UPDATE pipeline_jobs SET phyloseq_oid = %s WHERE id = '%s'",
            as.character(oid), job_id)
  )

  # Limpeza
  unlink(tmpdir, recursive = TRUE)

  message(sprintf("[dada2] Concluído — OID=%s ASVs=%d amostras=%d",
                  oid, n_asvs, nrow(meta_df)))

  list(
    phyloseq_oid = as.integer(oid),
    n_asvs       = n_asvs,
    n_samples    = nrow(meta_df),
    marker_type  = marker_type,
    reads_in     = sum(out[, 1], na.rm = TRUE),
    reads_out    = sum(out[, 2], na.rm = TRUE),
    samples_kept = nrow(meta_df),
    samples_dropped = n_removed
  )
}
