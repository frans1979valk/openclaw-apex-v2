#!/bin/bash
# Build alle services die gewijzigd zijn voor PostgreSQL migratie
set -e
echo "=== Building control_api ==="
docker compose build control_api
echo "=== Building apex_engine ==="
docker compose build apex_engine
echo "=== Building kimi_pattern_agent ==="
docker compose build kimi_pattern_agent
echo "=== Building jojo_analytics ==="
docker compose build jojo_analytics
echo ""
echo "=== Alle builds klaar. Start met: ==="
echo "docker compose up -d"
