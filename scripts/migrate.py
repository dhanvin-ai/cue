import os
from pathlib import Path

import psycopg
from psycopg import sql

root = Path(__file__).resolve().parents[1]


def main() -> None:
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'cue_app'")
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE ROLE cue_app LOGIN PASSWORD {}").format(
                        sql.Literal(os.environ["CUE_APP_DB_PASSWORD"])
                    )
                )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY)"
            )
            cursor.execute("SELECT 1 FROM schema_migrations WHERE version = 1")
            if cursor.fetchone() is None:
                cursor.execute((root / "migrations/001_foundation.sql").read_text())
                cursor.execute("INSERT INTO schema_migrations (version) VALUES (1)")


if __name__ == "__main__":
    main()
