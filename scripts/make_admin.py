"""Promote an existing account to admin (or create the first admin).

Usage:
  python3 scripts/make_admin.py <email> [--db data/morseweb.sqlite3]

The account must already exist (sign up through the web UI first);
this also marks the email verified so a fresh dev admin can log in
without the email round-trip.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--db", default="data/morseweb.sqlite3")
    args = parser.parse_args()

    storage.configure(args.db)
    user = storage.get_user_by_email(args.email.strip().lower())
    if user is None:
        raise SystemExit(f"No account with email {args.email}. Sign up first.")

    storage.update_user(user["id"], role="admin", email_verified=1)
    print(f"{user['name']} <{user['email']}> is now an admin.")


if __name__ == "__main__":
    main()
