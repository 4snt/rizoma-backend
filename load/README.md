# Testes de carga e estresse — Locust

Avaliam velocidade, tempo de resposta e estabilidade da API sob volume, e levam
a infra ao limite (estresse).

## Instalação

```bash
pip install locust          # ou: pip install -r api/requirements-dev.txt
```

## Desempenho / Carga (cenário de leitura)

```bash
# UI web interativa
locust -f load/locustfile.py --host http://localhost:8000
# abra http://localhost:8089 e defina nº de usuários + ramp-up

# Headless: 100 usuários, +10/s, 2 minutos
locust -f load/locustfile.py --host http://localhost:8000 \
       --headless -u 100 -r 10 -t 2m
```

Métricas observadas: RPS, p50/p95/p99 de latência, taxa de falhas.

## Estresse (achar o ponto de quebra)

Suba os usuários progressivamente até a API degradar (latência dispara ou erros aparecem):

```bash
locust -f load/locustfile.py StressUser --host http://localhost:8000 \
       --headless -u 500 -r 50 -t 3m
```

## Níveis sugeridos

| Nível      | Usuários | Ramp | Duração | Objetivo                        |
|------------|----------|------|---------|---------------------------------|
| Smoke      | 5        | 1/s  | 30s     | sanidade                        |
| Carga      | 50–100   | 10/s | 2–5 min | comportamento sob uso normal    |
| Estresse   | 300–800  | 50/s | 3–5 min | encontrar o limite de quebra    |

## Notas de ambiente

- Alvos de produção: respeite o timeout do Nginx Ingress (30 min) — análises
  pesadas (SpiecEasi) são assíncronas via fila, não no request HTTP.
- O `locustfile.py` usa só endpoints **GET públicos** (sem efeitos colaterais).
  Para carga autenticada, injete `Authorization: Bearer <jwt>` em `self.client`.
