-- Progresso real por etapa nos jobs + parâmetros DADA2 persistidos no projeto
DO $$
BEGIN
    -- Progresso reportado pelo R Worker durante a execução
    IF NOT EXISTS (SELECT FROM information_schema.columns
                   WHERE table_name='pipeline_jobs' AND column_name='progress_pct') THEN
        ALTER TABLE pipeline_jobs ADD COLUMN progress_pct INT NOT NULL DEFAULT 0;
    END IF;

    IF NOT EXISTS (SELECT FROM information_schema.columns
                   WHERE table_name='pipeline_jobs' AND column_name='progress_stage') THEN
        ALTER TABLE pipeline_jobs ADD COLUMN progress_stage TEXT;
    END IF;

    -- Parâmetros DADA2 escolhidos no cadastro do projeto
    IF NOT EXISTS (SELECT FROM information_schema.columns
                   WHERE table_name='projects' AND column_name='dada2_params') THEN
        ALTER TABLE projects ADD COLUMN dada2_params JSONB NOT NULL DEFAULT '{}';
    END IF;
END$$;
