#!/usr/bin/env bash
# update.sh — Update OpenClaw Apex to latest version
set -euo pipefail

echo "=== OpenClaw Apex — Update ==="

echo "[1/4] Git pull..."
git pull --rebase

echo "[2/4] Submodule update..."
git submodule update --init --recursive

echo "[3/4] Rebuild containers..."
docker compose build --no-cache

echo "[4/4] Restart services..."
docker compose up -d

echo ""
echo "Update gereed."
echo "Control API : http://127.0.0.1:8080/health"
echo "Runtime     : http://127.0.0.1:8090/health"
echo "Dashboard   : http://127.0.0.1:3000/"
