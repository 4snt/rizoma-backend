library(dada2)
library(phyloseq)

# Parâmetros DADA2 conforme MarkerConfig em CLAUDE.md.
# Os defaults dependem do marcador; o usuário pode sobrescrever via payload
# (campos dada2_params definidos no cadastro do projeto / aba DADA2).
.dada2_params <- function(marker_type, payload = list()) {
  # Helper: usa o valor do payload se presente e não-nulo, senão o default
  p <- function(key, default) {
    v <- payload[[key]]
    if (is.null(v) || (length(v) == 1 && is.na(v))) default else v
  }

  if (marker_type == "16S") {
    base <- list(
      trunc_len_f = 230L,
      trunc_len_r = 180L,
      ref_train   = "/refs/silva_nr99_v138.1_train_set.fa.gz",
      ref_species = "/refs/silva_species_v138.1.fa.gz",
      label       = "SILVA 138.1"
    )
  } else {                                 # ITS
    fasta <- .find_unite_fasta()
    base <- list(
      trunc_len_f = 0L,                    # ITS: comprimento variável, sem truncagem
      trunc_len_r = 0L,
      ref_train   = fasta,
      ref_species = NULL,
      label       = "UNITE"
    )
  }

  list(
    trunc_len_f    = as.integer(p("trunc_len_f", base$trunc_len_f)),
    trunc_len_r    = as.integer(p("trunc_len_r", base$trunc_len_r)),
    max_ee_f       = as.numeric(p("max_ee_f", 2)),
    max_ee_r       = as.numeric(p("max_ee_r", 2)),
    trunc_q        = as.integer(p("trunc_q", 2)),
    max_n          = as.integer(p("max_n", 0)),
    min_len        = as.integer(p("min_len", 50)),
    chimera_method = as.character(p("chimera_method", "consensus")),
    ref_train      = base$ref_train,
    ref_species    = base$ref_species,
    label          = base$label
  )
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
  params <- .dada2_params(marker_type, payload)

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

  pg_set_progress(con, job_id, 10, "Baixando FASTQs")
  for (i in seq_len(nrow(samples))) {
    pg_download_binary(con, samples$fastq_r1_oid[i], fnFs[i])
    pg_download_binary(con, samples$fastq_r2_oid[i], fnRs[i])
    message(sprintf("[dada2] Download %d/%d: %s", i, nrow(samples), smp_names[i]))
  }

  # ── 4. Filter and Trim ────────────────────────────────────────────────────
  filtFs <- setNames(file.path(filtered_d, paste0(smp_names, "_F_filt.fastq.gz")), smp_names)
  filtRs <- setNames(file.path(filtered_d, paste0(smp_names, "_R_filt.fastq.gz")), smp_names)

  pg_set_progress(con, job_id, 25, "Filtragem de qualidade (filterAndTrim)")
  message("[dada2] filterAndTrim...")
  if (params$trunc_len_f > 0) {
    out <- dada2::filterAndTrim(
      fnFs, filtFs, fnRs, filtRs,
      truncLen  = c(params$trunc_len_f, params$trunc_len_r),
      maxN = params$max_n, maxEE = c(params$max_ee_f, params$max_ee_r),
      truncQ = params$trunc_q, rm.phix = TRUE,
      compress = TRUE, multithread = TRUE
    )
  } else {
    # ITS: sem truncagem, usa minLen
    out <- dada2::filterAndTrim(
      fnFs, filtFs, fnRs, filtRs,
      maxN = params$max_n, maxEE = c(params$max_ee_f, params$max_ee_r),
      truncQ = params$trunc_q, rm.phix = TRUE,
      minLen = params$min_len,
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
  pg_set_progress(con, job_id, 45, "Aprendendo taxas de erro")
  message("[dada2] Aprendendo taxas de erro (forward)...")
  errF <- dada2::learnErrors(filtFs, multithread = TRUE)
  message("[dada2] Aprendendo taxas de erro (reverse)...")
  errR <- dada2::learnErrors(filtRs, multithread = TRUE)

  # ── 6. Denoising ──────────────────────────────────────────────────────────
  pg_set_progress(con, job_id, 65, "Inferência de ASVs (denoising)")
  message("[dada2] Denoising...")
  dadaFs <- dada2::dada(filtFs, err = errF, multithread = TRUE)
  dadaRs <- dada2::dada(filtRs, err = errR, multithread = TRUE)

  # ── 7. Merge paired reads ─────────────────────────────────────────────────
  pg_set_progress(con, job_id, 80, "Mesclando pares (merge)")
  message("[dada2] Merging pares...")
  mergers <- dada2::mergePairs(dadaFs, filtFs, dadaRs, filtRs, verbose = FALSE)

  # ── 8. Sequence table + chimera removal ───────────────────────────────────
  seqtab <- dada2::makeSequenceTable(mergers)
  rownames(seqtab) <- smp_filt

  pg_set_progress(con, job_id, 88, "Removendo quimeras")
  message("[dada2] Removendo quimeras...")
  seqtab_nc <- dada2::removeBimeraDenovo(seqtab, method = params$chimera_method, multithread = TRUE)

  n_asvs <- ncol(seqtab_nc)
  message(sprintf("[dada2] ASVs finais: %d", n_asvs))
  if (n_asvs == 0) stop("Nenhuma ASV após remoção de quimeras.")

  # ── 9. Assign taxonomy ────────────────────────────────────────────────────
  pg_set_progress(con, job_id, 95, sprintf("Classificação taxonômica (%s)", params$label))
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

  pg_set_progress(con, job_id, 100, "Concluído")
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
