-- Foto de perfil do Google (picture do userinfo endpoint)
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS avatar_url TEXT;

-- Autor do projeto (quem criou via POST /projects/)
ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL;
