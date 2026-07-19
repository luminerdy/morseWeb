"""Import a morsePi student's data directory into the morseWeb database.

morsePi keeps per-student files under data/students/<student>/:
  practice_progress.json, learning_state.json, timing not per-student,
  practice_attempts.jsonl, word_attempts.jsonl, bonus_attempts.jsonl

Usage:
  python3 scripts/import_morsepi_data.py <student_dir> [--db data/morseweb.sqlite3] [--slug pappy] [--name Pappy]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage

ATTEMPT_FILES = {
    "practice": "practice_attempts.jsonl",
    "word": "word_attempts.jsonl",
    "bonus": "bonus_attempts.jsonl",
}


def load_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def import_student(student_dir, slug, name):
    student_dir = Path(student_dir)
    counts = {"documents": 0, "attempts": 0}

    user_id = storage.ensure_user(slug=slug, name=name)
    storage.set_current_user(user_id)

    progress = load_json(student_dir / "practice_progress.json")
    if progress is not None:
        storage.set_document("practice_progress", progress)
        counts["documents"] += 1

    learning_state = load_json(student_dir / "learning_state.json")
    if learning_state is not None:
        storage.set_document("learning_state", learning_state)
        counts["documents"] += 1

    for kind, filename in ATTEMPT_FILES.items():
        path = student_dir / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            storage.append_attempt(kind, record)
            counts["attempts"] += 1

    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("student_dir", help="morsePi data/students/<student> directory")
    parser.add_argument("--db", default="data/morseweb.sqlite3")
    parser.add_argument("--slug", default=storage.DEFAULT_USER_SLUG)
    parser.add_argument("--name", default=storage.DEFAULT_USER_NAME)
    args = parser.parse_args()

    storage.configure(args.db)
    counts = import_student(args.student_dir, args.slug, args.name)
    print(f"Imported {counts['documents']} documents and {counts['attempts']} attempts "
          f"into {args.db} for user '{args.slug}'.")


if __name__ == "__main__":
    main()
