-- Habilita gerenciamento de ciclo de vida de LOs
CREATE EXTENSION IF NOT EXISTS lo;

DO $$
BEGIN
    -- Renomeia colunas de S3 keys para backup temporário
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='samples' AND column_name='fastq_r1_key') THEN
        ALTER TABLE samples RENAME COLUMN fastq_r1_key TO fastq_r1_key_old;
    END IF;

    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='samples' AND column_name='fastq_r2_key') THEN
        ALTER TABLE samples RENAME COLUMN fastq_r2_key TO fastq_r2_key_old;
    END IF;

    -- Adiciona colunas OID
    IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='samples' AND column_name='fastq_r1_oid') THEN
        ALTER TABLE samples ADD COLUMN fastq_r1_oid OID;
    END IF;

    IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='samples' AND column_name='fastq_r2_oid') THEN
        ALTER TABLE samples ADD COLUMN fastq_r2_oid OID;
    END IF;

    -- Adiciona OID do phyloseq nos jobs
    IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='pipeline_jobs' AND column_name='phyloseq_oid') THEN
        ALTER TABLE pipeline_jobs ADD COLUMN phyloseq_oid OID;
    END IF;

    -- Adiciona OID para modelos RF em analysis_results
    IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='analysis_results' AND column_name='result_oid') THEN
        ALTER TABLE analysis_results ADD COLUMN result_oid OID;
    END IF;
END$$;

-- Triggers de limpeza automática de LOs órfãos
DROP TRIGGER IF EXISTS lo_cleanup_samples_r1 ON samples;
CREATE TRIGGER lo_cleanup_samples_r1
  BEFORE UPDATE OR DELETE ON samples
  FOR EACH ROW EXECUTE FUNCTION lo_manage(fastq_r1_oid);

DROP TRIGGER IF EXISTS lo_cleanup_samples_r2 ON samples;
CREATE TRIGGER lo_cleanup_samples_r2
  BEFORE UPDATE OR DELETE ON samples
  FOR EACH ROW EXECUTE FUNCTION lo_manage(fastq_r2_oid);

DROP TRIGGER IF EXISTS lo_cleanup_jobs ON pipeline_jobs;
CREATE TRIGGER lo_cleanup_jobs
  BEFORE UPDATE OR DELETE ON pipeline_jobs
  FOR EACH ROW EXECUTE FUNCTION lo_manage(phyloseq_oid);
