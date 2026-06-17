library(DBI)
library(RPostgres)

pg_connect <- function() {
  dbConnect(
    RPostgres::Postgres(),
    host     = Sys.getenv("POSTGRES_HOST", "localhost"),
    port     = as.integer(Sys.getenv("POSTGRES_PORT", "5432")),
    dbname   = Sys.getenv("POSTGRES_DB", "bioinformatica"),
    user     = Sys.getenv("POSTGRES_USER", "r_worker"),
    password = Sys.getenv("POSTGRES_PASSWORD", "changeme")
  )
}

pg_set_status <- function(con, job_id, status, error_msg = NULL) {
  if (status == "running") {
    DBI::dbExecute(con,
      "UPDATE pipeline_jobs SET status = $1, started_at = NOW() WHERE id = $2",
      list(status, job_id)
    )
  } else if (status == "done") {
    DBI::dbExecute(con,
      "UPDATE pipeline_jobs SET status = $1, completed_at = NOW() WHERE id = $2",
      list(status, job_id)
    )
  } else {
    DBI::dbExecute(con,
      "UPDATE pipeline_jobs SET status = $1, completed_at = NOW(), error_msg = $2 WHERE id = $3",
      list(status, error_msg, job_id)
    )
  }
}

pg_set_progress <- function(con, job_id, pct, stage = NULL) {
  tryCatch(
    DBI::dbExecute(con,
      "UPDATE pipeline_jobs SET progress_pct = $1, progress_stage = $2 WHERE id = $3",
      list(as.integer(pct), stage, job_id)
    ),
    error = function(e) message("[progress] falha ao gravar progresso: ", conditionMessage(e))
  )
}

pg_save_result <- function(con, job_id, analysis_type, result_data) {
  DBI::dbExecute(con,
    "INSERT INTO analysis_results (job_id, analysis_type, result_data) VALUES ($1, $2, $3)",
    list(job_id, analysis_type, jsonlite::toJSON(result_data, auto_unbox = TRUE))
  )
}
