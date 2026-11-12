"""Import a harvest CSV into the database from the command line.

    python -m app.seed path/to/harvests.csv

Same format as Settings -> Import CSV: Date, Crop, Weight (g), plus optional
Variety and Notes columns. Safe to re-run: rows that already exist are skipped.
"""
import sys
from pathlib import Path

from . import db, importer


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__.strip())
        sys.exit(2)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"seed: {path} not found")
        sys.exit(1)
    db.init_db()
    result = importer.import_csv(path.read_text(encoding="utf-8-sig"))
    print(f"seed: {result['added']} added, {result['skipped']} already present")
    for e in result["errors"]:
        print("  ", e)


if __name__ == "__main__":
    main()
