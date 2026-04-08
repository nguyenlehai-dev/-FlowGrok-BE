#!/usr/bin/env bash

set -euo pipefail

ENVIRONMENT="${1:-}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"

case "$ENVIRONMENT" in
  staging|prod)
    ;;
  *)
    echo "Usage: $0 <staging|prod>"
    exit 1
    ;;
esac

if [[ "$SKIP_BACKUP" != "1" ]]; then
  BACKUP_NAME="backup-flowgrok-${ENVIRONMENT}-$(date +%F-%H%M%S).tar.gz"
  tar -czf "$BACKUP_NAME" flowgrok.db storage
  echo "Created backup: $BACKUP_NAME"
fi

docker compose build
docker compose up -d --build
docker compose ps

echo "Deployed backend stack for $ENVIRONMENT"
