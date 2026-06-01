source("utils/pg_helpers.R")
source("utils/es_helpers.R")
source("utils/minio_helpers.R")
source("analyses/deseq2.R")
source("analyses/ancombc.R")
source("analyses/maaslin2.R")
source("analyses/spieceasi.R")
source("analyses/random_forest.R")
source("analyses/gsea.R")
source("analyses/funguild.R")
source("analyses/picrust2.R")

con <- pg_connect()
DBI::dbExecute(con, "LISTEN new_job")
message("[worker] Aguardando jobs...")

# Análises que exigem phyloseq_key no payload
NEEDS_PHYLOSEQ <- c("deseq2", "ancombc2", "maaslin2", "spieceasi", "random_forest", "gsea", "funguild", "picrust2")

process_job <- function(job) {
  job_id   <- job$id
  job_type <- job$job_type
  payload  <- jsonlite::fromJSON(job$payload)

  # Valida payload antes de rodar
  if (job_type %in% NEEDS_PHYLOSEQ && (is.null(payload$phyloseq_key) || nchar(payload$phyloseq_key) == 0)) {
    pg_set_status(con, job_id, "failed",
      error_msg = paste0("payload inválido: 'phyloseq_key' é obrigatório para análise '", job_type, "'"))
    message(sprintf("[worker] Job %s rejeitado — phyloseq_key ausente", job_id))
    return(invisible(NULL))
  }

  message(sprintf("[worker] Iniciando job %s — tipo: %s", job_id, job_type))
  pg_set_status(con, job_id, "running")

  tryCatch({
    result <- switch(job_type,
      "deseq2"        = run_deseq2(payload, con),
      "ancombc2"      = run_ancombc(payload, con),
      "maaslin2"      = run_maaslin2(payload, con),
      "spieceasi"     = run_spieceasi(payload, con),
      "random_forest" = run_random_forest(payload, con),
      "gsea"          = run_gsea(payload, con),
      "funguild"      = run_funguild(payload, con),
      "picrust2"      = run_picrust2(payload, con),
      stop(paste("Tipo de job desconhecido:", job_type))
    )

    pg_save_result(con, job_id, job_type, result)
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
