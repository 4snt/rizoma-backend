-- Remove colunas legadas de S3 keys (renomeadas em 005_large_objects.sql)
-- Armazenamento migrou para PostgreSQL Large Objects (OID)
ALTER TABLE samples DROP COLUMN IF EXISTS fastq_r1_key_old;
ALTER TABLE samples DROP COLUMN IF EXISTS fastq_r2_key_old;
