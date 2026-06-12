source("utils/pg_helpers.R")
source("utils/es_helpers.R")
source("utils/pg_storage.R")
source("utils/ncbi_taxonomy.R")
source("analyses/deseq2.R")
source("analyses/ancombc.R")
source("analyses/maaslin2.R")
source("analyses/spieceasi.R")
source("analyses/random_forest.R")
source("analyses/gsea.R")
source("analyses/funguild.R")
source("analyses/picrust2.R")
source("analyses/metagenomics.R")
source("analyses/dada2_silva.R")

con <- pg_connect()
DBI::dbExecute(con, "LISTEN new_job")
message("[worker] Aguardando jobs...")

# Análises que exigem phyloseq_oid na coluna pipeline_jobs
NEEDS_PHYLOSEQ <- c("deseq2", "ancombc2", "maaslin2", "spieceasi",
                    "random_forest", "gsea", "funguild", "picrust2",
                    "metagenomics_pipeline")
# dada2_pipeline gera o phyloseq — não exige um como entrada

process_job <- function(job) {
  job_id   <- job$id
  job_type <- job$job_type
  payload  <- jsonlite::fromJSON(job$payload)

  # Valida payload antes de rodar
  phyloseq_oid <- DBI::dbGetQuery(con,
    sprintf("SELECT phyloseq_oid FROM pipeline_jobs WHERE id = '%s'", job_id))[[1]]
  if (job_type %in% NEEDS_PHYLOSEQ && (is.null(phyloseq_oid) || is.na(phyloseq_oid))) {
    pg_set_status(con, job_id, "failed",
      error_msg = paste0("payload inválido: 'phyloseq_oid' é obrigatório para análise '", job_type, "'"))
    message(sprintf("[worker] Job %s rejeitado — phyloseq_oid ausente", job_id))
    return(invisible(NULL))
  }
  payload$phyloseq_oid <- phyloseq_oid
  # Sempre disponíveis para todas as análises que precisem
  payload$job_id      <- job_id
  payload$project_id  <- as.character(job$project_id)

  message(sprintf("[worker] Iniciando job %s — tipo: %s", job_id, job_type))
  pg_set_status(con, job_id, "running")

  tryCatch({
    result <- switch(job_type,
      "deseq2"                = run_deseq2(payload, con),
      "ancombc2"              = run_ancombc(payload, con),
      "maaslin2"              = run_maaslin2(payload, con),
      "spieceasi"             = run_spieceasi(payload, con),
      "random_forest"         = run_random_forest(payload, con),
      "gsea"                  = run_gsea(payload, con),
      "funguild"              = run_funguild(payload, con),
      "picrust2"              = run_picrust2(payload, con),
      "metagenomics_pipeline" = run_metagenomics(payload, con),
      "dada2_pipeline"        = run_dada2_silva(payload, con),
      stop(paste("Tipo de job desconhecido:", job_type))
    )

    # metagenomics_pipeline salva seus próprios sub-resultados e retorna NULL
    if (!is.null(result)) {
      pg_save_result(con, job_id, job_type, result)
    }
    pg_set_status(con, job_id, "done")
    message(sprintf("[worker] Job %s concluído.", job_id))

  }, error = function(e) {
    pg_set_status(con, job_id, "failed", error_msg = conditionMessage(e))
    message(sprintf("[worker] ERRO no job %s: %s", job_id, conditionMessage(e)))
  })
}

repeat {
  RPostgres::postgresWaitForNotify(con, timeout = 30)

  job <- DBI::dbGetQuery(con, "
    SELECT id, project_id, job_type, payload
    FROM pipeline_jobs
    WHERE status = 'queued'
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
  ")

  if (nrow(job) > 0) process_job(job)
}
