from __future__ import annotations

from sqlalchemy import text


TABLE_COLUMN_UPDATES: dict[str, list[tuple[str, str]]] = {
    "users": [
        ("updated_at", "DATETIME"),
    ],
    "api_keys": [
        ("name", "VARCHAR"),
        ("key_hash", "VARCHAR"),
        ("key_preview", "VARCHAR"),
        ("rate_limit_per_minute", "INTEGER DEFAULT 60"),
        ("last_used_at", "DATETIME"),
        ("last_used_ip", "VARCHAR"),
        ("expires_at", "DATETIME"),
        ("revoked_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ],
    "proxies": [
        ("protocol", "VARCHAR DEFAULT 'http'"),
        ("country", "VARCHAR"),
        ("provider", "VARCHAR"),
        ("latency_ms", "INTEGER"),
        ("fail_count", "INTEGER DEFAULT 0"),
        ("is_active", "BOOLEAN DEFAULT 1"),
        ("last_checked_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ],
    "profiles": [
        ("description", "TEXT"),
        ("cookie_source_type", "VARCHAR"),
        ("cookie_import_name", "VARCHAR"),
        ("cookie_imported_at", "DATETIME"),
        ("storage_path", "VARCHAR"),
        ("cache_path", "VARCHAR"),
        ("headless", "BOOLEAN DEFAULT 1"),
        ("concurrency_limit", "INTEGER DEFAULT 1"),
        ("provider_config", "JSON"),
        ("last_used_at", "DATETIME"),
        ("last_health_check_at", "DATETIME"),
        ("is_enabled", "BOOLEAN DEFAULT 1"),
        ("updated_at", "DATETIME"),
    ],
    "generation_jobs": [
        ("requested_by_user_id", "VARCHAR"),
        ("api_key_id", "VARCHAR"),
        ("provider", "VARCHAR"),
        ("job_type", "VARCHAR"),
        ("request_payload", "JSON"),
        ("priority", "INTEGER DEFAULT 100"),
        ("retry_count", "INTEGER DEFAULT 0"),
        ("worker_id", "VARCHAR"),
        ("proxy_snapshot", "JSON"),
        ("browser_session_path", "VARCHAR"),
        ("result_payload", "JSON"),
        ("started_at", "DATETIME"),
        ("finished_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ],
}


def _sqlite_table_columns(connection, table_name: str) -> set[str]:
    rows = connection.execute(text(f"PRAGMA table_info('{table_name}')")).fetchall()
    return {row[1] for row in rows}


def run_sqlite_migrations(engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        existing_tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }

        for table_name, columns in TABLE_COLUMN_UPDATES.items():
            if table_name not in existing_tables:
                continue

            existing_columns = _sqlite_table_columns(connection, table_name)
            for column_name, column_sql in columns:
                if column_name in existing_columns:
                    continue
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
                )
