"""Trusted operator grants a verified source principal to a tenant member."""

import argparse
import os
from uuid import UUID

import firebase_admin
import psycopg
from firebase_admin import auth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("firebase_uid")
    parser.add_argument("principal", help="e.g. email:owner:person@example.com or github:repo:123")
    args = parser.parse_args()
    if args.principal.startswith("email:owner:"):
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(options={"projectId": os.environ["FIREBASE_PROJECT_ID"]})
        user = auth.get_user(args.firebase_uid)
        if not user.email_verified or user.email.casefold() != args.principal.removeprefix("email:owner:").casefold():
            raise ValueError("Delegated email principal must match this user's verified Firebase email")
    elif not args.principal.startswith(("github:repo:", "slack:channel:", "linear:team:")):
        raise ValueError("Unsupported principal type")
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        member = database.execute(
            "SELECT 1 FROM users WHERE tenant_id = %s AND firebase_uid = %s",
            (args.tenant_id, args.firebase_uid),
        ).fetchone()
        if member is None:
            raise ValueError("User is not a tenant member")
        database.execute(
            "INSERT INTO user_principals (tenant_id, firebase_uid, principal) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (args.tenant_id, args.firebase_uid, args.principal),
        )


if __name__ == "__main__":
    main()
