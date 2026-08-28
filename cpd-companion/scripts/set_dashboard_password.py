#!/usr/bin/env python3
"""Set the dashboard password: prompt, bcrypt-hash, write to cpd-companion/.env.

    & ".\.venv\Scripts\python.exe" .\scripts\set_dashboard_password.py

The plaintext is never echoed, never written to disk, and never passed as a
command-line argument (argv is visible to other processes). Only the hash is
stored. Writes to cpd-companion/.env specifically — the repo-root .env belongs
to the old n8n starter kit and is not read by this app.
"""

import getpass
import os
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
HASH_KEY = "CPD_DASHBOARD_PASSWORD_HASH"
PLAIN_KEY = "CPD_DASHBOARD_PASSWORD"


def main() -> int:
    try:
        import bcrypt
    except ImportError:
        print("bcrypt is not installed in this interpreter — run this with "
              "cpd-companion/.venv/Scripts/python.exe", file=sys.stderr)
        return 1

    if not ENV_PATH.exists():
        print(f"missing {ENV_PATH}", file=sys.stderr)
        return 1

    password = getpass.getpass("New dashboard password: ")
    if len(password) < 8:
        print("Too short — use at least 8 characters.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Confirm: "):
        print("Passwords did not match — nothing changed.", file=sys.stderr)
        return 1

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    assert bcrypt.checkpw(password.encode(), hashed.encode()), "hash failed to verify"
    del password

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    wrote_hash = False
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{HASH_KEY}="):
            out.append(f"{HASH_KEY}={hashed}\n")
            wrote_hash = True
        elif stripped.startswith(f"{PLAIN_KEY}="):
            # A leftover plaintext password would be a second, weaker way in.
            out.append(f"{PLAIN_KEY}=\n")
        elif "TEMPORARY deployment-test hash" in line or (
                stripped.startswith("#") and "REPLACE with Ron's own" in line):
            continue  # drop the deployment-time warning comment
        else:
            out.append(line)
    if not wrote_hash:
        out.append(f"{HASH_KEY}={hashed}\n")

    # Write via a temp file in the same directory, then replace, so an
    # interrupted write cannot leave a truncated .env behind.
    tmp = ENV_PATH.with_suffix(".env.tmp")
    tmp.write_text("".join(out), encoding="utf-8")
    os.replace(tmp, ENV_PATH)

    print(f"Updated {HASH_KEY} in {ENV_PATH}")
    print("Restart the app for it to take effect:")
    print(r"  pwsh -NoProfile -File .\scripts\start-cpd.ps1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
