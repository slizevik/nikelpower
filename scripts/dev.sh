#!/usr/bin/env sh
set -e
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — set OPENAI_API_KEY before ingestion."
fi

docker compose up -d --build
echo "Services:"
echo "  Neo4j Browser: http://localhost:7474"
echo "  Streamlit UI:  http://localhost:8501"
docker compose ps
