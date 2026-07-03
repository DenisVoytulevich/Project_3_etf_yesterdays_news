#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/etf-daily-briefing}"

cd "${APP_DIR}"
git pull origin main

export COMPOSE_FILE="${APP_DIR}/vps/docker-compose.yml"
docker compose -f "${COMPOSE_FILE}" build --pull
docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans
docker image prune -f

echo "ETF Daily Briefing deploy complete"
