#!/usr/bin/env bash
set -euo pipefail

echo "[1/3] Docker check..."
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found. Installing..."
  curl -fsSL https://get.docker.com | sh
fi

echo "[2/3] Build..."
docker compose build

echo "[3/3] Up..."
docker compose up -d

echo "Done."
echo "Control API: http://127.0.0.1:8080/health"
echo "Dashboard  : http://127.0.0.1:3000/"
