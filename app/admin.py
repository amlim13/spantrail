"""Admin CLI for the spantrail operator.

Usage:
  python admin.py tenant-create --name "Acme" --email a@acme.com [--plan free]
  python admin.py tenant-list
  python admin.py key-rotate --tenant <uuid>
"""
import sys
import argparse

import auth
import db


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    tc = sub.add_parser("tenant-create")
    tc.add_argument("--name", required=True)
    tc.add_argument("--email")
    tc.add_argument("--plan", default="free")

    sub.add_parser("tenant-list")

    kr = sub.add_parser("key-rotate")
    kr.add_argument("--tenant", required=True)

    args = p.parse_args()
    db.apply_schema()

    if args.cmd == "tenant-create":
        row, raw = auth.create_tenant(args.name, args.email, args.plan)
        print(f"tenant_id : {row['id']}")
        print(f"name      : {row['name']}")
        print(f"email     : {row['email']}")
        print(f"plan      : {row['plan']}")
        print(f"api_key   : {raw}")
        print("\nStore the api_key now. It is not recoverable (only a hash is kept).")

    elif args.cmd == "tenant-list":
        with db.cursor() as cur:
            cur.execute(
                "SELECT id, name, email, plan, status, created_at FROM tenants ORDER BY created_at DESC"
            )
            for r in cur.fetchall():
                print(
                    f"{r['id']}  {r['status']:<10} {r['plan']:<6} {r['name']:<28} {r['email'] or ''}"
                )

    elif args.cmd == "key-rotate":
        row, raw = auth.rotate_key(args.tenant)
        if not row:
            print("tenant not found")
            sys.exit(1)
        print(f"tenant_id : {row['id']}")
        print(f"api_key   : {raw}")


if __name__ == "__main__":
    main()
