#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env}"
POSTGRES_DB="${POSTGRES_DB:-flowgrok}"
POSTGRES_USER="${POSTGRES_USER:-flowgrok}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-flowgrok_dev_password}"
POSTGRES_PORT="${POSTGRES_PORT:-5433}"
TARGET_DATABASE_URL="${TARGET_DATABASE_URL:-postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}}"
TARGET_DATABASE_URL_INTERNAL="${TARGET_DATABASE_URL_INTERNAL:-postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}}"
SOURCE_DATABASE_URL="${SOURCE_DATABASE_URL:-sqlite:///./flowgrok.db}"
SKIP_MIGRATE="${SKIP_MIGRATE:-0}"

echo "Preparing local PostgreSQL runtime..."

if [[ -f "$ENV_FILE" ]]; then
  cp "$ENV_FILE" "${ENV_FILE}.backup.$(date +%F-%H%M%S)"
fi

cat > "$ENV_FILE" <<EOF
APP_ENV=development
SECRET_KEY=${SECRET_KEY:-change-me-in-production}
DATABASE_URL=$TARGET_DATABASE_URL_INTERNAL
REDIS_URL=${REDIS_URL:-redis://redis:6379/0}
POSTGRES_DB=$POSTGRES_DB
POSTGRES_USER=$POSTGRES_USER
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
EOF

echo "Starting compose with postgres profile..."
docker compose --profile postgres up -d postgres redis

echo "Waiting for local PostgreSQL to become ready..."
for _ in $(seq 1 30); do
  if docker compose --profile postgres exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! docker compose --profile postgres exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
  echo "PostgreSQL is not ready"
  exit 1
fi

echo "Bootstrapping API once against target DATABASE_URL so tables exist..."
docker compose --profile postgres run --rm \
  -e DATABASE_URL="$TARGET_DATABASE_URL_INTERNAL" \
  api python - <<'PY'
from app.db.base import Base
from app.db.database import engine
import app.models.core

Base.metadata.create_all(bind=engine)
print("tables ready")
PY

if [[ "$SKIP_MIGRATE" != "1" ]]; then
  echo "Migrating SQLite data into local PostgreSQL..."
  docker compose --profile postgres run --rm \
    -e SOURCE_DATABASE_URL="$SOURCE_DATABASE_URL" \
    -e TARGET_DATABASE_URL="$TARGET_DATABASE_URL_INTERNAL" \
    api python scripts/migrate_sqlite_to_postgres.py
fi

echo "Starting API against local PostgreSQL..."
docker compose --profile postgres up -d api

echo "Done"
echo "Verify with:"
echo "  curl http://127.0.0.1:8080/api/health"
echo "Expected dialect: postgres"
echo "Direct DB access from host:"
echo "  $TARGET_DATABASE_URL"
