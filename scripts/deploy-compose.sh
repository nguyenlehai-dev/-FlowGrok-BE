#!/usr/bin/env bash

set -euo pipefail

ENVIRONMENT="${1:-}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"

if docker info >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker compose)
elif sudo -n docker info >/dev/null 2>&1; then
  DOCKER_COMPOSE=(sudo docker compose)
else
  echo "Docker daemon is not accessible for user $(id -un)."
  echo "Run with a user in the docker group or configure passwordless sudo for docker."
  exit 1
fi

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

"${DOCKER_COMPOSE[@]}" build
"${DOCKER_COMPOSE[@]}" up -d --build
"${DOCKER_COMPOSE[@]}" ps

echo "Deployed backend stack for $ENVIRONMENT"
