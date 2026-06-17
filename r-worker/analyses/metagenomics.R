library(phyloseq)
library(vegan)
library(jsonlite)

# Detecta coluna de grupo no sample_data
.detect_group_col <- function(meta) {
  candidates <- c("treatment_group", "SampleType", "Group", "group", "Treatment", "Condition")
  found <- intersect(candidates, colnames(meta))
  if (length(found) > 0) return(found[1])
  colnames(meta)[1]
}

# Normaliza nomes de colunas taxonômicas para lowercase sem prefixos
.normalize_tax_names <- function(df) {
  nms <- tolower(colnames(df))
  nms <- sub("^k__?|^kingdom_?", "domain", nms)
  nms <- sub("^p__?|^phylum_?", "phylum", nms)
  nms <- sub("^c__?|^class_?", "class", nms)
  nms <- sub("^o__?|^order_?", "order", nms)
  nms <- sub("^f__?|^family_?", "family", nms)
  nms <- sub("^g__?|^genus_?", "genus", nms)
  nms <- sub("^s__?|^species_?", "species", nms)
  colnames(df) <- nms
  df
}

run_metagenomics <- function(payload, con) {
  message("[metagenomics] Iniciando pipeline...")
  job_id <- payload$job_id

  pg_set_progress(con, job_id, 10, "Carregando phyloseq")
  # 1. Carrega phyloseq
  ps <- pg_download_rds(con, payload$phyloseq_oid)
  n_taxa <- ntaxa(ps)
  n_samples <- nsamples(ps)
  message(sprintf("[metagenomics] phyloseq: %d taxa, %d amostras", n_taxa, n_samples))

  if (n_samples < 2) {
    stop("phyloseq precisa ter ao menos 2 amostras para análise de metagenômica")
  }

  # 2. OTU e taxonomy
  otu <- as.data.frame(otu_table(ps))
  if (!taxa_are_rows(ps)) otu <- t(otu)

  tax_df <- tryCatch(
    .normalize_tax_names(as.data.frame(tax_table(ps))),
    error = function(e) data.frame()
  )

  meta <- tryCatch(as.data.frame(sample_data(ps)), error = function(e) data.frame())
  smp_names <- colnames(otu)

  group_col <- if (ncol(meta) > 0) .detect_group_col(meta) else NA_character_
  groups <- if (!is.na(group_col) && group_col %in% colnames(meta)) {
    setNames(as.character(meta[[group_col]]), rownames(meta))
  } else {
    setNames(rep("all", n_samples), smp_names)
  }

  # ── 3. ASV Table ──────────────────────────────────────────────────────
  tax_levels    <- c("domain", "phylum", "class", "order", "family", "genus", "species")
  sample_totals <- colSums(otu)

  asv_rows <- lapply(rownames(otu), function(asv) {
    smp_vals <- as.list(as.numeric(otu[asv, ]))
    names(smp_vals) <- smp_names

    rel_abund <- setNames(
      lapply(smp_names, function(s) {
        tot <- sample_totals[[s]]
        cnt <- as.numeric(otu[asv, s])
        if (!is.na(tot) && tot > 0) round(cnt / tot * 100, 4) else 0
      }),
      smp_names
    )

    tax_row <- if (nrow(tax_df) > 0 && asv %in% rownames(tax_df)) {
      as.list(tax_df[asv, intersect(tax_levels, colnames(tax_df)), drop = FALSE][1, ])
    } else {
      list()
    }
    tax_row <- tax_row[!sapply(tax_row, function(x) is.na(x) || x == "NA" || x == "")]

    list(
      taxon         = asv,
      taxonomy      = tax_row,
      samples       = smp_vals,
      rel_abundance = rel_abund,
      total         = sum(as.numeric(otu[asv, ]), na.rm = TRUE)
    )
  })

  pg_save_result(con, job_id, "asv_table", list(
    rows             = asv_rows,
    sample_names     = smp_names,
    available_levels = tax_levels
  ))
  message("[metagenomics] asv_table salvo")
  pg_set_progress(con, job_id, 40, "Diversidade alfa/beta")

  # ── 4. Alpha diversity ────────────────────────────────────────────────
  otu_t <- t(otu)  # amostras × taxa

  shannon    <- vegan::diversity(otu_t, index = "shannon")
  simpson    <- vegan::diversity(otu_t, index = "simpson")
  invsimpson <- vegan::diversity(otu_t, index = "invsimpson")
  richness   <- vegan::specnumber(otu_t)

  N        <- rowSums(otu_t)
  S        <- richness
  margalef <- ifelse(N > 1, (S - 1) / log(N), 0)
  pielou   <- ifelse(S > 1, shannon / log(S), 0)

  alpha_pts <- lapply(smp_names, function(s) {
    list(
      sample_id        = s,
      treatment_group  = unname(groups[s]),
      shannon          = unname(shannon[s]),
      simpson          = unname(simpson[s]),
      invsimpson       = unname(invsimpson[s]),
      richness         = unname(richness[s]),
      margalef         = unname(margalef[s]),
      pielou           = unname(pielou[s])
    )
  })

  kruskal_res <- NULL
  if (length(unique(groups)) >= 2) {
    kruskal_res <- tryCatch({
      kt <- kruskal.test(shannon ~ factor(groups[smp_names]))
      list(
        metric    = "shannon",
        statistic = unname(kt$statistic),
        p_value   = kt$p.value,
        df        = unname(kt$parameter)
      )
    }, error = function(e) NULL)
  }

  # ── 5. Beta diversity + PERMANOVA + PCoA ─────────────────────────────
  beta_metrics  <- c("bray", "jaccard")
  beta_results  <- list()
  permanova_res <- list()
  ordinations   <- list()

  for (bm in beta_metrics) {
    dist_mat <- tryCatch(vegan::vegdist(otu_t, method = bm), error = function(e) NULL)
    if (is.null(dist_mat)) next

    dm <- as.matrix(dist_mat)
    beta_results[[bm]] <- list(
      metric       = bm,
      matrix       = lapply(seq_len(nrow(dm)), function(i) as.list(unname(dm[i, ]))),
      sample_names = smp_names
    )

    if (length(unique(groups)) >= 2) {
      perm <- tryCatch(
        vegan::adonis2(dist_mat ~ groups[smp_names], permutations = 999),
        error = function(e) NULL
      )
      if (!is.null(perm)) {
        permanova_res[[bm]] <- list(
          metric  = bm,
          r2      = unname(perm$R2[1]),
          p_value = unname(perm$`Pr(>F)`[1]),
          df      = unname(perm$Df[1])
        )
      }
    }

    # PCoA
    k_axes <- min(3, n_samples - 1)
    pcoa <- tryCatch(cmdscale(dist_mat, k = k_axes, eig = TRUE), error = function(e) NULL)
    if (!is.null(pcoa) && !is.null(pcoa$points)) {
      eig     <- if (!is.null(pcoa$eig)) pcoa$eig else rep(1, k_axes)
      eig_pos <- pmax(eig, 0)
      var_exp <- if (sum(eig_pos) > 0) round(eig_pos / sum(eig_pos) * 100, 2) else rep(0, length(eig))

      pts <- lapply(seq_along(smp_names), function(i) {
        s   <- smp_names[i]
        idx <- which(rownames(pcoa$points) == s)
        if (length(idx) == 0) return(NULL)
        pt <- pcoa$points[idx, , drop = FALSE]
        list(
          sample_id       = s,
          treatment_group = unname(groups[s]),
          axis1           = unname(pt[1, 1]),
          axis2           = if (ncol(pt) >= 2) unname(pt[1, 2]) else 0,
          axis3           = if (ncol(pt) >= 3) unname(pt[1, 3]) else 0
        )
      })
      pts <- pts[!sapply(pts, is.null)]

      ordinations[[length(ordinations) + 1]] <- list(
        type             = "pcoa",
        beta_metric      = bm,
        variance_explained = as.list(var_exp[seq_len(min(3, length(var_exp)))]),
        points           = pts,
        permanova        = permanova_res[[bm]]
      )
    }
  }

  pg_save_result(con, job_id, "diversity", list(
    alpha            = alpha_pts,
    kruskal          = kruskal_res,
    beta             = beta_results,
    permanova        = permanova_res,
    available_metrics = beta_metrics,
    level_computed   = "asv"
  ))
  message("[metagenomics] diversity salvo")

  pg_save_result(con, job_id, "ordination", ordinations)
  message("[metagenomics] ordination salvo")
  pg_set_progress(con, job_id, 75, "Biomarcadores (ANCOM-BC2)")

  # ── 6. Biomarcadores (ANCOM-BC2) ─────────────────────────────────────
  biomarkers_result <- list(method = "none", level = "asv", markers = list(), note = "")

  if (length(unique(groups)) >= 2 && nrow(tax_df) > 0 && "genus" %in% colnames(tax_df)) {
    ancombc_out <- tryCatch({
      sample_data(ps)[[group_col]] <- factor(groups[smp_names])
      ANCOMBC::ancombc2(
        data            = ps,
        tax_level       = "Genus",
        fix_formula     = paste0("~ ", group_col),
        p_adj_method    = "BH",
        pseudo_sens     = FALSE,
        prv_cut         = 0.10,
        lib_cut         = 1000,
        s0_perc         = 0.05,
        group           = group_col,
        struc_zero      = FALSE,
        neg_lb          = FALSE,
        iter_control    = list(tol = 0.01, max_iter = 20, verbose = FALSE),
        em_control      = list(tol = 1e-5, max_iter = 100),
        lme_control     = NULL,
        mdfdr_control   = list(fwer_ctrl_method = "BH", B = 100),
        trend_control   = list(contrast = NULL, node = NULL, solver = "ECOS", B = 100)
      )
    }, error = function(e) {
      message("[metagenomics] ANCOM-BC erro: ", conditionMessage(e))
      NULL
    })

    if (!is.null(ancombc_out)) {
      res_df   <- ancombc_out$res
      lfc_cols <- grep("^lfc_",  colnames(res_df), value = TRUE)
      q_cols   <- grep("^q_",    colnames(res_df), value = TRUE)
      diff_cols <- grep("^diff_", colnames(res_df), value = TRUE)

      if (length(lfc_cols) > 0 && length(q_cols) > 0) {
        lfc_col  <- lfc_cols[1]
        q_col    <- q_cols[1]
        sig_mask <- if (length(diff_cols) > 0) res_df[[diff_cols[1]]] else res_df[[q_col]] < 0.05
        sig_df   <- res_df[sig_mask, ]

        markers <- lapply(seq_len(nrow(sig_df)), function(i) {
          list(
            taxon      = sig_df$taxon[i],
            taxonomy   = list(genus = sig_df$taxon[i]),
            effect_size = unname(sig_df[[lfc_col]][i]),
            p_value    = unname(sig_df[[q_col]][i]),
            direction  = if (sig_df[[lfc_col]][i] > 0) "enriched" else "depleted"
          )
        })

        biomarkers_result <- list(
          method     = "ancombc2",
          level      = "genus",
          markers    = markers,
          comparison = sub("^lfc_", "", lfc_col)
        )
      }
    }
  } else {
    biomarkers_result$note <- "Requer >= 2 grupos e taxonomia de gênero disponível"
  }

  pg_save_result(con, job_id, "biomarkers", biomarkers_result)
  message("[metagenomics] biomarkers salvo")

  pg_set_progress(con, job_id, 100, "Concluído")
  message("[metagenomics] Pipeline concluído.")
  NULL  # sinaliza ao worker para não chamar pg_save_result externo
}
