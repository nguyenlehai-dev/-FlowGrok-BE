#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TARGET_DATABASE_URL="${TARGET_DATABASE_URL:-}"
SOURCE_DATABASE_URL="${SOURCE_DATABASE_URL:-sqlite:///./flowgrok.db}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"

if [[ -z "$TARGET_DATABASE_URL" ]]; then
  echo "Missing TARGET_DATABASE_URL"
  echo "Example:"
  echo 'TARGET_DATABASE_URL=postgresql+psycopg://postgres:password@host:5432/flowgrok ./scripts/backup_migrate_verify.sh'
  exit 1
fi

if [[ "$SKIP_BACKUP" != "1" ]]; then
  BACKUP_NAME="backup-before-migrate-$(date +%F-%H%M%S).tar.gz"
  tar -czf "$BACKUP_NAME" flowgrok.db storage .env 2>/dev/null || tar -czf "$BACKUP_NAME" flowgrok.db storage
  echo "Created backup: $BACKUP_NAME"
fi

echo "Migrating rows from source DB to target DB..."
SOURCE_DATABASE_URL="$SOURCE_DATABASE_URL" \
TARGET_DATABASE_URL="$TARGET_DATABASE_URL" \
python3 scripts/migrate_sqlite_to_postgres.py

echo "Writing .env for target runtime..."
if [[ -f ".env" ]]; then
  cp .env ".env.backup.$(date +%F-%H%M%S)"
fi

cat > .env <<EOF
APP_ENV=production
SECRET_KEY=${SECRET_KEY:-change-me-in-production}
DATABASE_URL=$TARGET_DATABASE_URL
REDIS_URL=${REDIS_URL:-redis://redis:6379/0}
EOF

echo "Verifying backend imports with target DATABASE_URL..."
DATABASE_URL="$TARGET_DATABASE_URL" python3 - <<'PY'
import main
from app.db.database import SQLALCHEMY_DATABASE_URL
print("import ok", main.app.title)
print("database_url", SQLALCHEMY_DATABASE_URL)
PY

echo "Done"
echo "Next step:"
echo "  docker compose up -d --build"
