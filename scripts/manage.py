#!/usr/bin/env python3
"""
Cortex KB — management CLI.

Does NOT require the app to be running. Connects directly to Postgres.
Reads DB DSN from .env (or pass --dsn explicitly).

Commands
--------
  create-key  --label <label> [--role admin|editor|viewer]  Create new API key
  list-keys                                                  List all API keys
  revoke-key  --id <key-id>                                  Deactivate a key
  recover     --secret <APP_SECRET_KEY>                      Emergency admin key (same as /admin/recover-key)

Examples
--------
  python scripts/manage.py create-key --label "ci-runner" --role editor
  python scripts/manage.py list-keys
  python scripts/manage.py revoke-key --id <uuid>
  python scripts/manage.py recover --secret change-me-32-chars-minimum
"""
import argparse
import hashlib
import os
import secrets
import sys
import uuid
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

try:
    from sqlalchemy import create_engine, text
except ImportError:
    sys.exit("sqlalchemy not installed — run: pip install sqlalchemy psycopg2-binary")

GREEN = "\033[92m"; RED = "\033[91m"; CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"

def get_engine(dsn: str):
    # Convert asyncpg DSN to sync psycopg2 if needed
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    return create_engine(dsn)


def cmd_create_key(args):
    engine = get_engine(args.dsn)
    with engine.connect() as c:
        tenant = c.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
        if not tenant:
            sys.exit(f"{RED}No tenant found. Run /bootstrap first.{RESET}")

        raw = f"cortex_{secrets.token_urlsafe(32)}"
        kh  = hashlib.sha256(raw.encode()).hexdigest()
        kid = str(uuid.uuid4())
        c.execute(
            text("INSERT INTO api_keys (id, tenant_id, key_hash, label, role, is_active) "
                 "VALUES (:id, :tid, :kh, :label, :role, true)"),
            {"id": kid, "tid": tenant, "kh": kh, "label": args.label, "role": args.role},
        )
        c.commit()

    print(f"\n{GREEN}{BOLD}API key created!{RESET}")
    print(f"  Key ID : {kid}")
    print(f"  Label  : {args.label}")
    print(f"  Role   : {args.role}")
    print(f"\n{BOLD}  Raw key (save this — shown once):{RESET}")
    print(f"\n  {CYAN}{raw}{RESET}\n")


def cmd_list_keys(args):
    engine = get_engine(args.dsn)
    with engine.connect() as c:
        rows = c.execute(
            text("SELECT id, label, role, is_active, last_used, created_at FROM api_keys ORDER BY created_at DESC")
        ).fetchall()

    if not rows:
        print("No API keys found.")
        return

    print(f"\n{'ID':<38} {'Label':<20} {'Role':<8} {'Active':<7} {'Last used'}")
    print("-" * 90)
    for r in rows:
        active = f"{GREEN}yes{RESET}" if r.is_active else f"{RED}no{RESET}"
        last = str(r.last_used)[:19] if r.last_used else "never"
        print(f"{r.id:<38} {r.label:<20} {r.role:<8} {active:<16} {last}")
    print()


def cmd_revoke_key(args):
    engine = get_engine(args.dsn)
    with engine.connect() as c:
        result = c.execute(
            text("UPDATE api_keys SET is_active = false WHERE id = :id"),
            {"id": args.id},
        )
        c.commit()
        if result.rowcount == 0:
            sys.exit(f"{RED}Key not found: {args.id}{RESET}")

    print(f"{GREEN}Key {args.id} revoked.{RESET}")


def cmd_recover(args):
    """Emergency: create admin key without needing an existing key."""
    engine = get_engine(args.dsn)
    expected = os.environ.get("APP_SECRET_KEY", "")
    if not expected or not secrets.compare_digest(args.secret, expected):
        sys.exit(f"{RED}Wrong secret — must match APP_SECRET_KEY in .env{RESET}")
    if expected in ("change-me-32-chars-minimum", "change-me-insecure-default"):
        sys.exit(f"{RED}APP_SECRET_KEY is still the default — set a real value first{RESET}")

    # Reuse create-key logic
    args.label = "recovered-admin"
    args.role  = "admin"
    cmd_create_key(args)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    default_dsn = os.environ.get("POSTGRES_DSN", "postgresql://cortex:cortex@localhost:5432/cortex_kb")

    p = argparse.ArgumentParser(description="Cortex KB management CLI")
    p.add_argument("--dsn", default=default_dsn, help="Postgres DSN (default: from .env)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # create-key
    ck = sub.add_parser("create-key", help="Create a new API key")
    ck.add_argument("--label", required=True, help="Human-readable label")
    ck.add_argument("--role", default="admin", choices=["admin", "editor", "viewer"])

    # list-keys
    sub.add_parser("list-keys", help="List all API keys")

    # revoke-key
    rk = sub.add_parser("revoke-key", help="Revoke an API key by ID")
    rk.add_argument("--id", required=True, help="Key UUID to revoke")

    # recover
    rc = sub.add_parser("recover", help="Emergency: create admin key using APP_SECRET_KEY")
    rc.add_argument("--secret", required=True, help="Value of APP_SECRET_KEY from your .env")

    args = p.parse_args()
    {"create-key": cmd_create_key, "list-keys": cmd_list_keys,
     "revoke-key": cmd_revoke_key, "recover": cmd_recover}[args.cmd](args)


if __name__ == "__main__":
    main()
