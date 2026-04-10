from __future__ import annotations

import os
import sys

from sqlalchemy import MetaData, Table, create_engine, select


DEFAULT_SOURCE_URL = "sqlite:///./flowgrok.db"


def _ordered_tables(metadata: MetaData) -> list[str]:
    preferred_order = [
        "users",
        "api_keys",
        "proxies",
        "profiles",
        "profile_runtime_settings",
        "profile_antidetect_settings",
        "profile_cookie_imports",
        "generation_jobs",
        "job_artifacts",
    ]
    existing = {table.name for table in metadata.sorted_tables}
    return [name for name in preferred_order if name in existing]


def main() -> int:
    source_url = os.getenv("SOURCE_DATABASE_URL", DEFAULT_SOURCE_URL)
    target_url = os.getenv("TARGET_DATABASE_URL")

    if not target_url:
        print("Missing TARGET_DATABASE_URL")
        return 1

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)

    source_metadata = MetaData()
    target_metadata = MetaData()

    source_metadata.reflect(bind=source_engine)
    target_metadata.reflect(bind=target_engine)

    table_names = _ordered_tables(source_metadata)
    if not table_names:
        print("No tables found to migrate")
        return 1

    migrated_counts: dict[str, int] = {}

    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        for table_name in table_names:
            if table_name not in target_metadata.tables:
                print(f"Skipping missing target table: {table_name}")
                continue

            source_table = Table(table_name, source_metadata, autoload_with=source_engine)
            target_table = Table(table_name, target_metadata, autoload_with=target_engine)

            rows = [dict(row._mapping) for row in source_conn.execute(select(source_table))]
            if not rows:
                migrated_counts[table_name] = 0
                print(f"{table_name}: 0 rows")
                continue

            target_conn.execute(target_table.delete())
            target_conn.execute(target_table.insert(), rows)
            migrated_counts[table_name] = len(rows)
            print(f"{table_name}: {len(rows)} rows migrated")

    print("Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
