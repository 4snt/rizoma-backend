library(DBI)
library(RPostgres)

pg_download_rds <- function(conn, oid, local_path = tempfile(fileext = ".rds")) {
  result <- dbGetQuery(conn, sprintf("SELECT lo_get(%s)", oid))
  writeBin(result[[1]][[1]], local_path)
  readRDS(local_path)
}

# Baixa um Large Object binário (ex.: FASTQ .gz) para um arquivo local
pg_download_binary <- function(conn, oid, dest_path) {
  result <- dbGetQuery(conn, sprintf("SELECT lo_get(%s)", oid))
  writeBin(result[[1]][[1]], dest_path)
  invisible(dest_path)
}

pg_upload_rds <- function(conn, obj) {
  tmp <- tempfile(fileext = ".rds")
  saveRDS(obj, tmp)
  on.exit(unlink(tmp))

  raw_data <- readBin(tmp, "raw", file.info(tmp)$size)

  oid <- dbGetQuery(conn, "SELECT lo_create(0)")[[1]]
  dbExecute(conn, sprintf("SELECT lo_put(%s, 0, $1)", oid),
            params = list(raw_data))
  return(oid)
}
