# Estratégia de Testes — Rizoma

Mapa das 9 categorias de teste e onde cada uma vive nos dois repositórios
(`rizoma-backend` e `rizoma` frontend).

| # | Categoria | Onde | Como rodar | Estado |
|---|-----------|------|-----------|--------|
| 1 | **Unitários** | `api/tests/unit/` (pytest) · `lib/__tests__/` (Vitest) | `cd api && pytest tests/unit` · `npm test` | ✅ executável |
| 2 | **Integração** | `api/tests/integration/` (httpx + app ASGI) | `cd api && pytest tests/integration` | ✅ parte roda; ciclo com banco é `skip` sem Postgres |
| 3 | **Sistema / E2E** | `e2e/smoke.spec.ts` (Playwright) | `npm run e2e` (app no ar) | 🟡 smoke roda; fluxo logado documentado/`skip` |
| 4 | **Regressão** | `.github/workflows/ci.yml` (ambos os repos) | automático em push/PR | ✅ roda pytest + vitest + build + audit |
| 5 | **Aceitação (UAT)** | [`UAT.md`](./UAT.md) | execução humana | 📄 roteiros por persona |
| 6 | **Desempenho / Carga** | `load/locustfile.py` | `locust -f load/locustfile.py` | 🟡 script pronto (requer API no ar) |
| 7 | **Estresse** | `load/locustfile.py` (`StressUser`) | ver [`load/README.md`](../../load/README.md) | 🟡 script pronto |
| 8 | **Segurança** | [`SECURITY-TESTING.md`](./SECURITY-TESTING.md) + testes de auth | `bandit -r app` · `npm audit` · pytest | ✅/📄 misto |
| 9 | **Usabilidade** | [`USABILITY.md`](./USABILITY.md) | teste com usuários + heurística | 📄 roteiro + SUS |

Legenda: ✅ executável agora · 🟡 script/scaffold pronto (precisa de infra) · 📄 documento.

## Quickstart

```bash
# Backend (unit + integração que não exigem banco)
cd rizoma-backend/api
pip install -r requirements-dev.txt
pytest -q

# Frontend (unit)
cd "rizoma - Frontend"
npm install
npm test
```

Para a suíte de integração completa (ciclo de projeto), aponte para um Postgres
de teste via variáveis `POSTGRES_*` antes de rodar `pytest` — os testes marcados
com a fixture `db_pool` deixam de ser `skip`.
