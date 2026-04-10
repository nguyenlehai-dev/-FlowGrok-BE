# Database Migration Guide

## Supported Runtime Modes

- Local/dev: `SQLite` via `sqlite:///./flowgrok.db`
- Staging/prod: `PostgreSQL` or `Supabase Postgres` via `DATABASE_URL`

## Environment Setup

Copy `.env.example` and adjust:

```bash
cp .env.example .env
```

Example Postgres:

```env
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/flowgrok
```

Example local Docker Postgres from this repo:

```env
POSTGRES_DB=flowgrok
POSTGRES_USER=flowgrok
POSTGRES_PASSWORD=flowgrok_dev_password
```

Compose runtime inside the `api` container should use:

```env
DATABASE_URL=postgresql+psycopg://flowgrok:flowgrok_dev_password@postgres:5432/flowgrok
```

Direct access from the host machine can use:

```env
DATABASE_URL=postgresql+psycopg://flowgrok:flowgrok_dev_password@localhost:5433/flowgrok
```

## SQLite -> PostgreSQL Migration

1. Ensure target Postgres database already exists
2. Start backend once against target `DATABASE_URL` so SQLAlchemy creates tables
3. Run migration script:

```bash
cd /home/vpsroot/projects/backend/-FlowGrok-BE
SOURCE_DATABASE_URL=sqlite:///./flowgrok.db \
TARGET_DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/flowgrok \
python3 scripts/migrate_sqlite_to_postgres.py
```

## One-shot Backup + Migrate + Verify

```bash
cd /home/vpsroot/projects/backend/-FlowGrok-BE
TARGET_DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/flowgrok \
./scripts/backup_migrate_verify.sh
```

## Switch Local Runtime From SQLite To Docker Postgres

This repo also supports a local Postgres service behind the compose profile `postgres`.

```bash
cd /home/vpsroot/projects/backend/-FlowGrok-BE
chmod +x scripts/switch_to_local_postgres.sh
./scripts/switch_to_local_postgres.sh
```

This flow:

- rewrites `.env` to a local Postgres `DATABASE_URL`
- starts `postgres` and `redis`
- creates tables
- migrates rows from local SQLite unless `SKIP_MIGRATE=1`
- starts `api` against the new Postgres target

Quick verify:

```bash
curl http://127.0.0.1:8080/api/health
```

Expected response:

```json
{"status":"ok","service":"flowgrok-api","database":{"dialect":"postgresql","url":"postgresql+psycopg://flowgrok:***@postgres:5432/flowgrok"}}
```

This flow:

- backs up `flowgrok.db` and `storage/`
- migrates DB rows into target Postgres
- rewrites `.env` with target `DATABASE_URL`
- verifies backend import against the target DB

## Notes

- Script truncates target tables before insert
- Files under `storage/` are not copied by the script; only DB rows are migrated
- Run backup before migration
- `docker compose --profile postgres up -d` is opt-in; current SQLite runtime remains unchanged until you run the switch script

## Recommended Production Layout

- PostgreSQL / Supabase: users, api keys, profiles, proxies, settings, jobs, artifacts metadata
- Filesystem or object storage: raw cookies, storage state, screenshots, generated outputs
