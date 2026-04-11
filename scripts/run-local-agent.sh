#!/usr/bin/env bash

set -euo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"

python3 -m uvicorn app.local_agent.main:app --host "$HOST" --port "$PORT"
