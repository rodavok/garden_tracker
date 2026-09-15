"""Import a harvest CSV into the database.

    python -m app.seed                # imports data/seed/garden_produce.csv
    python -m app.seed path/to.csv    # imports another file

Safe to re-run: rows that already exist are skipped.
"""
import sys
from pathlib import Path

from . import db, importer
from .config import SEED_CSV


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SEED_CSV
    if not path.exists():
        print(f"seed: {path} not found, nothing to do")
        return
    db.init_db()
    result = importer.import_csv(path.read_text(encoding="utf-8-sig"))
    print(f"seed: {result['added']} added, {result['skipped']} already present")
    for e in result["errors"]:
        print("  ", e)


if __name__ == "__main__":
    main()
