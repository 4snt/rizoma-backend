-- BioProject opcional nos projetos (para listar SRR runs associados)
ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS bioproject_accession VARCHAR(20);
