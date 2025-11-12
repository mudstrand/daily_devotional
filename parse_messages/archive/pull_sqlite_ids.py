#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB_PATH = "daily_devotional.db"  # change to your .sqlite/.db file
OUT_FILE = "sqlite_message_ids.txt"  # output file path


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        # Distinct, non-null, non-empty IDs
        cur.execute("""
            SELECT DISTINCT message_id
            FROM devotionals
            WHERE message_id IS NOT NULL
              AND TRIM(message_id) <> ''
            ORDER BY message_id
        """)
        rows = cur.fetchall()
    finally:
        conn.close()

    ids = [r[0] for r in rows]
    Path(OUT_FILE).write_text("\n".join(ids) + "\n", encoding="utf-8")
    print(f"Wrote {len(ids)} IDs to {OUT_FILE}")


if __name__ == "__main__":
    main()
