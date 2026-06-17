# Testes de Segurança — Rizoma

Identificam vulnerabilidades e brechas exploráveis. Combina **testes automatizados**
(no CI) com um **checklist** de verificação manual.

---

## 1. Automatizado

### Backend — análise estática (bandit)
```bash
cd api
pip install bandit
bandit -r app -ll        # -ll: só severidade média/alta
```
Procura por: SQL string-format, segredos hardcoded, uso inseguro de subprocess, etc.

### Dependências
```bash
# Frontend
npm audit --omit=dev
# Backend
pip install pip-audit && pip-audit -r api/requirements.txt
```

### Testes de autenticação (pytest)
Já cobertos na suíte:
- `tests/unit/test_security.py` — JWT: round-trip, **adulteração → JWTError**,
  **segredo errado → JWTError**, **expiração → JWTError**.
- `tests/integration/test_auth_gating.py` — endpoints de projeto/admin **exigem
  Bearer** (403 sem token).
- `tests/unit/test_permissions.py` — edição/exclusão restrita a **admin ou criador**.

---

## 2. Checklist manual (OWASP-lite)

| # | Verificação | Esperado | Status |
|---|-------------|----------|--------|
| A1 | Acesso sem login a rotas protegidas | redireciona p/ /login (middleware) | ☐ |
| A2 | Login com e-mail fora de `@ufvjm.edu.br` | negado (403 / signIn false) | ☐ |
| A3 | Usuário novo sem convite | 403 NotInvited | ☐ |
| A4 | Researcher tentando ação de admin (ex.: /admin/users) | 403 | ☐ |
| A5 | Researcher excluindo projeto de outro | 403 (admin-ou-criador) | ☐ |
| A6 | JWT expirado/adulterado em chamada autenticada | 401 | ☐ |
| A7 | CORS: origem não listada | bloqueada (CORS_ORIGINS) | ☐ |
| A8 | Segredos (JWT_SECRET, GOOGLE_*) só via env, nunca no código/commits | confirmado | ☐ |
| A9 | Upload: arquivo acima do limite (`max_upload_size_mb`) | 413 | ☐ |
| A10 | SQL injection em parâmetros (ex.: code de projeto) | queries parametrizadas (asyncpg) | ☐ |
| A11 | Headers de segurança no Ingress (HSTS, X-Content-Type-Options) | revisar Nginx | ☐ |

---

## 3. Notas de arquitetura relevantes

- **Queries parametrizadas:** API usa asyncpg com `$1,$2…` (sem string-format).
  ⚠ O R Worker usa `sprintf` em alguns SELECTs por `id` (UUID validado) — manter
  apenas com valores controlados (UUIDs/inteiros), nunca com entrada de usuário livre.
- **Segredos:** `JWT_SECRET`, `GOOGLE_CLIENT_ID/SECRET`, credenciais PG vêm de env
  (`.env`/Coolify), fora do versionamento.
- **Domínio restrito:** login limitado a `@ufvjm.edu.br` + convite (NextAuth + backend).
