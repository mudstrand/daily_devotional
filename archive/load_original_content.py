#!/usr/bin/env python3
import sqlite3
from pathlib import Path
import os

ORIG_DIR = Path("orig")  # directory with <message_id>.txt files
TABLE = "devotionals"  # table name
db_devotional = os.getenv("DEVOTIONAL_DB")


def main():
    conn = sqlite3.connect(db_devotional)
    cur = conn.cursor()

    # speed up batch updates
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")

    updated = 0
    missing = 0

    for p in ORIG_DIR.glob("*.txt"):
        message_id = p.stem  # filename without .txt
        content = p.read_text(encoding="utf-8")

        cur.execute(
            f"UPDATE {TABLE} SET original_content = ? WHERE message_id = ?",
            (content, message_id),
        )
        if cur.rowcount == 0:
            missing += 1
        else:
            updated += cur.rowcount

    conn.commit()
    conn.close()
    print(f"Done. Updated {updated} rows. Files with no matching message_id: {missing}")


if __name__ == "__main__":
    main()
