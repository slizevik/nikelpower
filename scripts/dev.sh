#!/usr/bin/env sh
set -e
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — заполните ключи Yandex в .env"
fi

# Лёгкая сборка: только Neo4j + Streamlit UI
docker compose up -d --build neo4j backend
echo "Services:"
echo "  Neo4j Browser: http://localhost:7474"
echo "  Streamlit UI:  http://localhost:8501"
echo ""
echo "Worker (тяжёлая сборка): docker compose --profile worker up -d --build worker"
docker compose ps
