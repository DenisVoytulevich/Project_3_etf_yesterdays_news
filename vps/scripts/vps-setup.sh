#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/etf-daily-briefing}"
REPO_URL="${REPO_URL:-https://github.com/DenisVoytulevich/Project_3_etf_yesterdays_news.git}"

if [[ ! -d "${APP_DIR}/.git" ]]; then
  sudo mkdir -p "${APP_DIR}"
  sudo chown "$(whoami):$(whoami)" "${APP_DIR}"
  git clone "${REPO_URL}" "${APP_DIR}"
fi

cd "${APP_DIR}"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Создан ${APP_DIR}/.env — заполните переменные и перезапустите deploy."
  exit 1
fi

mkdir -p credentials data/reports data/structure_cache
bash "${APP_DIR}/vps/scripts/deploy.sh"
