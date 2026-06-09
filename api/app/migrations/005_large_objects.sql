-- Habilita gerenciamento de ciclo de vida de LOs
CREATE EXTENSION IF NOT EXISTS lo;

-- Renomeia colunas de S3 keys para backup temporário
ALTER TABLE samples
  RENAME COLUMN fastq_r1_key TO fastq_r1_key_old;

ALTER TABLE samples
  RENAME COLUMN fastq_r2_key TO fastq_r2_key_old;

-- Adiciona colunas OID
ALTER TABLE samples
  ADD COLUMN fastq_r1_oid OID,
  ADD COLUMN fastq_r2_oid OID;

-- Após migrar dados existentes, executar:
-- UPDATE samples SET fastq_r1_oid = NULL WHERE fastq_r1_key_old IS NOT NULL; -- dados legados não migrável automaticamente
-- ALTER TABLE samples DROP COLUMN fastq_r1_key_old;
-- ALTER TABLE samples DROP COLUMN fastq_r2_key_old;

-- Adiciona OID do phyloseq nos jobs
ALTER TABLE pipeline_jobs
  ADD COLUMN phyloseq_oid OID;

-- Adiciona OID para modelos RF em analysis_results
ALTER TABLE analysis_results
  ADD COLUMN result_oid OID;

-- Triggers de limpeza automática de LOs órfãos
CREATE TRIGGER lo_cleanup_samples_r1
  BEFORE UPDATE OR DELETE ON samples
  FOR EACH ROW EXECUTE FUNCTION lo_manage(fastq_r1_oid);

CREATE TRIGGER lo_cleanup_samples_r2
  BEFORE UPDATE OR DELETE ON samples
  FOR EACH ROW EXECUTE FUNCTION lo_manage(fastq_r2_oid);

CREATE TRIGGER lo_cleanup_jobs
  BEFORE UPDATE OR DELETE ON pipeline_jobs
  FOR EACH ROW EXECUTE FUNCTION lo_manage(phyloseq_oid);
