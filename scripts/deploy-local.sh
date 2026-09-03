#!/usr/bin/env bash
# deploy-local.sh — fluxo de deploy direto no servidor (homelab).
#
# Builda a imagem Docker do serviço a partir do checkout local, importa no
# containerd do microk8s (o cluster roda com imagePullPolicy=Never) e reinicia
# o deployment. Uso típico após um `git pull` nos repos:
#
#   ./scripts/deploy-local.sh            # sobe frontend + api
#   ./scripts/deploy-local.sh frontend   # só o frontend
#   ./scripts/deploy-local.sh api        # só a api
#
# Pré-requisitos: docker, microk8s e kubectl acessíveis do usuário corrente
# (sudo pede só pro microk8s ctr).
set -euo pipefail

DEPLOY_TARGET="${1:-all}"
KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config-microk8s}"
export KUBECONFIG
NAMESPACE="bioinformatica"

FRONTEND_DIR="${RIZOMA_FRONTEND_DIR:-$HOME/projects/rizoma}"
BACKEND_DIR="${RIZOMA_BACKEND_DIR:-$HOME/projects/rizoma-backend}"

# NEXT_PUBLIC_* ficam embutidos no bundle JS em build-time (Dockerfile do
# frontend usa localhost:8000 como default) — sem passar isso aqui, todo
# fetch feito PELO NAVEGADOR (laudos, membros, amostras...) tenta bater no
# localhost de quem acessa, não no servidor. Login continua funcionando
# porque o NextAuth roda no servidor e lê API_URL (var separada, não
# NEXT_PUBLIC_*) — foi exatamente esse sintoma que mascarou o bug como se
# fosse renovação de token.
NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-https://rizoma.${DOMAIN:-flipafile.com}}"
NEXT_PUBLIC_WS_URL="${NEXT_PUBLIC_WS_URL:-wss://rizoma.${DOMAIN:-flipafile.com}}"

import_and_rollout() {
  local image="$1" deployment="$2"
  echo "==> importando ${image} no containerd do microk8s"
  docker save "${image}" | sudo microk8s ctr --namespace k8s.io images import -
  echo "==> reiniciando deployment/${deployment}"
  kubectl -n "${NAMESPACE}" rollout restart "deployment/${deployment}"
  kubectl -n "${NAMESPACE}" rollout status "deployment/${deployment}" --timeout=300s
}

deploy_frontend() {
  local sha
  sha=$(git -C "${FRONTEND_DIR}" rev-parse --short HEAD)
  echo "==> build rizoma-frontend:local (master@${sha})"
  docker build -q -t rizoma-frontend:local -t "rizoma-frontend:git-${sha}" \
    --build-arg "NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}" \
    --build-arg "NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}" \
    "${FRONTEND_DIR}"
  import_and_rollout rizoma-frontend:local bio-frontend
}

deploy_api() {
  local sha
  sha=$(git -C "${BACKEND_DIR}" rev-parse --short HEAD)
  echo "==> build rizoma-api:local (master@${sha})"
  docker build -q -t rizoma-api:local -t "rizoma-api:git-${sha}" -f "${BACKEND_DIR}/api/Dockerfile" "${BACKEND_DIR}/api"
  import_and_rollout rizoma-api:local bio-api
}

case "${DEPLOY_TARGET}" in
  frontend) deploy_frontend ;;
  api)      deploy_api ;;
  all)      deploy_frontend; deploy_api ;;
  *) echo "uso: $0 [frontend|api|all]" >&2; exit 64 ;;
esac

echo "==> estado final dos pods:"
kubectl -n "${NAMESPACE}" get pods
