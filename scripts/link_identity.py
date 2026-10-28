"""Trusted operator links a verified vendor person to a Firebase team member."""

import argparse
import os
from uuid import UUID, NAMESPACE_URL, uuid5

import firebase_admin
import psycopg
from firebase_admin import auth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("firebase_uid")
    parser.add_argument("alias", help="github:user:ID, slack:person:ID, linear:person:ID, or gmail:person:EMAIL")
    args = parser.parse_args()
    if not args.alias.startswith(("github:user:", "slack:person:", "linear:person:", "gmail:person:")):
        raise ValueError("Unsupported person alias")
    if args.alias.startswith("gmail:person:"):
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(options={"projectId": os.environ["FIREBASE_PROJECT_ID"]})
        user = auth.get_user(args.firebase_uid)
        if not user.email_verified or user.email.casefold() != args.alias.removeprefix("gmail:person:").casefold():
            raise ValueError("Gmail identity must match this user's verified Firebase email")
    canonical_id = uuid5(NAMESPACE_URL, f"cue:{args.tenant_id}:person:{args.firebase_uid}")
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        if database.execute("SELECT 1 FROM users WHERE tenant_id = %s AND firebase_uid = %s",
                            (args.tenant_id, args.firebase_uid)).fetchone() is None:
            raise ValueError("User is not a tenant member")
        database.execute("INSERT INTO identity_claims (tenant_id, alias, firebase_uid) "
                         "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                         (args.tenant_id, args.alias, args.firebase_uid))
        claim = database.execute("SELECT firebase_uid FROM identity_claims WHERE tenant_id = %s AND alias = %s",
                                 (args.tenant_id, args.alias)).fetchone()
        if claim[0] != args.firebase_uid:
            raise ValueError("Alias is already linked to another member")
        database.execute("INSERT INTO entities (tenant_id, id, kind) VALUES (%s, %s, 'person') "
                         "ON CONFLICT DO NOTHING", (args.tenant_id, canonical_id))
        row = database.execute("SELECT entity_id FROM entity_aliases WHERE tenant_id = %s AND alias = %s",
                               (args.tenant_id, args.alias)).fetchone()
        if row and row[0] != canonical_id:
            old_id = row[0]
            old, new = f"person:{old_id}", f"person:{canonical_id}"
            database.execute("INSERT INTO identity_entity_map (tenant_id, from_id, to_id) "
                             "VALUES (%s, %s, %s) ON CONFLICT (tenant_id, from_id) "
                             "DO UPDATE SET to_id = EXCLUDED.to_id", (args.tenant_id, old_id, canonical_id))
            database.execute("UPDATE entity_aliases SET entity_id = %s WHERE tenant_id = %s AND alias = %s",
                             (canonical_id, args.tenant_id, args.alias))
            database.execute("UPDATE memory_documents SET actors = array_replace(actors, %s, %s), "
                             "objects = array_replace(objects, %s, %s), "
                             "facts = CASE WHEN facts->>'owner_id' = %s THEN jsonb_set(facts, '{owner_id}', to_jsonb(%s::text)) "
                             "ELSE facts END WHERE tenant_id = %s",
                             (old, new, old, new, old, new, args.tenant_id))
            database.execute(
                "INSERT INTO memory_edges (tenant_id, event_id, source_entity, predicate, target, target_label, "
                "valid_from, valid_to, visibility, principals) "
                "SELECT tenant_id, event_id, CASE WHEN source_entity = %s THEN %s ELSE source_entity END, "
                "predicate, CASE WHEN target = %s THEN %s ELSE target END, target_label, "
                "valid_from, valid_to, visibility, principals FROM memory_edges "
                "WHERE tenant_id = %s AND (source_entity = %s OR target = %s) ON CONFLICT DO NOTHING",
                (old, new, old, new, args.tenant_id, old, old),
            )
            database.execute("DELETE FROM memory_edges WHERE tenant_id = %s AND (source_entity = %s OR target = %s)",
                             (args.tenant_id, old, old))
        elif not row:
            database.execute("INSERT INTO entity_aliases (tenant_id, alias, entity_id) VALUES (%s, %s, %s)",
                             (args.tenant_id, args.alias, canonical_id))


if __name__ == "__main__":
    main()
