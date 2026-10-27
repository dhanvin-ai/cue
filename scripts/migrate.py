import os
from pathlib import Path

import psycopg
from psycopg import sql

root = Path(__file__).resolve().parents[1]


def main() -> None:
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            for role, password in (
                ("cue_app", "CUE_APP_DB_PASSWORD"),
                ("cue_ingest", "CUE_INGEST_DB_PASSWORD"),
            ):
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                if cursor.fetchone() is None:
                    cursor.execute(
                        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                            sql.Identifier(role), sql.Literal(os.environ[password])
                        )
                    )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY)"
            )
            for path in sorted((root / "migrations").glob("*.sql")):
                version = int(path.name.split("_", 1)[0])
                cursor.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
                if cursor.fetchone() is None:
                    cursor.execute(path.read_text())
                    cursor.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))


if __name__ == "__main__":
    main()
