import argparse
from uuid import UUID

from cue.connectors.backfill import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill a Cue connector connection")
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("connection_id", type=UUID)
    args = parser.parse_args()
    print(f"Published {run(args.tenant_id, args.connection_id)} snapshots")


if __name__ == "__main__":
    main()
