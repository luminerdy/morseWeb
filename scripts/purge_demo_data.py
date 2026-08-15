"""Delete demo accounts (and their documents/attempts) past retention.

Demo accounts (see auth.demo_or_login_required, app.start_demo) are
throwaway - no email, no password, created for the no-signup try-it
flow. Run periodically (deploy/morseweb-purge-demo.timer) so they
don't accumulate.

Usage:
  python3 scripts/purge_demo_data.py [--hours 24] [--db data/morseweb.sqlite3]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--db", default="data/morseweb.sqlite3")
    args = parser.parse_args()

    storage.configure(args.db)
    count = storage.purge_demo_users(args.hours)
    print(f"Purged {count} demo account(s) older than {args.hours}h.")


if __name__ == "__main__":
    main()
