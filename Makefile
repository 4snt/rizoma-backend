# Rizoma — atalhos de desenvolvimento.
# `make` sozinho lista os alvos.

COMPOSE ?= docker compose
DC_API  := $(COMPOSE) exec api

.DEFAULT_GOAL := help
.PHONY: help up up-worker down logs migrate migration test psql reset seed

help: ## Lista os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Sobe postgres + minio + api (sem o R Worker)
	$(COMPOSE) up -d

up-worker: ## Sobe tudo, inclusive o R Worker (build de ~20 min na primeira vez)
	$(COMPOSE) --profile worker up -d

down: ## Derruba os containers (preserva os volumes)
	$(COMPOSE) --profile worker down

logs: ## Segue os logs da API
	$(COMPOSE) logs -f api

migrate: ## Aplica as migrations pendentes (alembic upgrade head)
	$(DC_API) alembic upgrade head

migration: ## Cria uma migration nova:  make migration m="add samples table"
	@test -n "$(m)" || { echo 'uso: make migration m="mensagem"'; exit 1; }
	$(DC_API) alembic revision --autogenerate -m "$(m)"

test: ## Roda a suite de testes
	$(DC_API) pytest

psql: ## Abre um psql como dono do schema
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-api_user} -d $${POSTGRES_DB:-rizoma}

reset: ## APAGA os volumes, sobe do zero e migra (destrói os dados locais)
	$(COMPOSE) --profile worker down -v
	$(COMPOSE) up -d
	@echo "aguardando o banco e a API subirem..."
	@sleep 8
	$(MAKE) migrate

seed: ## Popula o banco com dados de exemplo (duas orgs + tokens de teste)
	$(DC_API) python -m scripts.seed_mvp
