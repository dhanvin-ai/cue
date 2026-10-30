"""Create monthly event-log partitions before each month starts (and during deploys)."""

import argparse
import os
from datetime import date

import psycopg
from psycopg import sql

from _local_env import load_local_env


def month_offset(today: date, offset: int) -> date:
    month = today.year * 12 + today.month - 1 + offset
    return date(month // 12, month % 12 + 1, 1)


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--months-back", type=int, default=12)
    args = parser.parse_args()
    if not 0 <= args.months_back <= 36:
        parser.error("--months-back must be between 0 and 36")
    today = date.today()
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        for offset in range(-args.months_back, 3):
            start, end = month_offset(today, offset), month_offset(today, offset + 1)
            name = f"event_log_{start:%Y_%m}"
            database.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} PARTITION OF event_log "
                    "FOR VALUES FROM ({}) TO ({}) PARTITION BY HASH (tenant_id)"
                ).format(sql.Identifier(name), sql.Literal(start), sql.Literal(end))
            )
            for remainder in range(4):
                database.execute(
                    sql.SQL(
                        "CREATE TABLE IF NOT EXISTS {} PARTITION OF {} "
                        "FOR VALUES WITH (MODULUS 4, REMAINDER {})"
                    ).format(
                        sql.Identifier(f"{name}_{remainder}"),
                        sql.Identifier(name),
                        sql.Literal(remainder),
                    )
                )


if __name__ == "__main__":
    main()
