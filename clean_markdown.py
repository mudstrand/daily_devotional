#!/usr/bin/env python3
import argparse
import sqlite3
from typing import Optional
import os

DEFAULT_TABLE = "devotionals"
DEFAULT_COLUMN = "prayer"

devotional_db = os.getenv("DEVOTIONAL_DB")


def clean_text(text: Optional[str]) -> Optional[str]:
    """
    Remove '*' and '_' and normalize whitespace.
    """
    if text is None:
        return None
    cleaned = text.replace("*", "").replace("_", "")

    # Collapse multiple spaces
    while "  " in cleaned:
        cleaned = cleaned.replace("  ", " ")

    # Trim spaces around line breaks (one logical line per DB line)
    cleaned = "\n".join(part.strip() for part in cleaned.splitlines())

    # Final trim
    cleaned = cleaned.strip()
    return cleaned


def main():
    ap = argparse.ArgumentParser(
        description="Interactively remove '*' and '_' from a chosen text column of your SQLite table (per-row commit)."
    )
    ap.add_argument(
        "--db",
        default=devotional_db,
        help="Path to SQLite DB",
    )
    ap.add_argument(
        "--table", default=DEFAULT_TABLE, help="Table name (default: devotionals)"
    )
    ap.add_argument(
        "--column", default=DEFAULT_COLUMN, help="Column to clean (default: prayer)"
    )
    ap.add_argument(
        "--id-column",
        default="message_id",
        help="Primary key column (default: message_id)",
    )
    ap.add_argument(
        "--limit", type=int, default=0, help="Preview at most N rows (0 = all)"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Preview only, do not write any changes"
    )
    args = ap.parse_args()

    # Basic validation for the column name to avoid SQL injection via identifiers
    # Only allow simple identifiers: letters, digits, underscore
    import re

    ident_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    for ident, label in [
        (args.table, "table"),
        (args.column, "column"),
        (args.id_column, "id-column"),
    ]:
        if not ident_re.match(ident):
            raise ValueError(f"Invalid {label} name: {ident}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Fetch candidates that contain '*' or '_' in the chosen column
    sql = f"""
        SELECT {args.id_column} AS pk, subject, {args.column} AS col_value
        FROM {args.table}
        WHERE {args.column} IS NOT NULL
          AND (instr({args.column}, '*') > 0 OR instr({args.column}, '_') > 0)
        ORDER BY {args.id_column}
    """
    if args.limit > 0:
        sql += f" LIMIT {args.limit}"

    rows = cur.execute(sql).fetchall()
    if not rows:
        print(f"No rows with '*' or '_' found in {args.table}.{args.column}.")
        conn.close()
        return

    print(f"Found {len(rows)} candidate rows in {args.table}.{args.column}.\n")

    updated = 0
    skipped = 0
    apply_all = False

    try:
        for i, r in enumerate(rows, start=1):
            pk = r["pk"]
            subject = r.get("subject") if isinstance(r, dict) else r["subject"]
            old = r["col_value"] or ""
            new = clean_text(old)

            if new == old:
                continue

            sep = "=" * 80
            print(sep)
            print(f"[{i}/{len(rows)}] {args.id_column}: {pk}")
            if subject:
                print(f"Subject: {subject}")
            print(f"Column : {args.column}")
            print("- Old value:")
            print(old)
            print("- New value (cleaned):")
            print(new)
            print(sep)

            if args.dry_run:
                skipped += 1
                continue

            if not apply_all:
                while True:
                    resp = (
                        input("Apply change? [y]es / [n]o / [a]ll / [q]uit: ")
                        .strip()
                        .lower()
                    )
                    if resp in {"y", "n", "a", "q"}:
                        break
                    print("Please enter y, n, a, or q.")
                if resp == "q":
                    print("Quitting. Already-applied changes remain committed.")
                    break
                elif resp == "a":
                    apply_all = True
                elif resp == "n":
                    skipped += 1
                    continue

            # Apply and commit this single row
            cur.execute(
                f"UPDATE {args.table} SET {args.column} = ? WHERE {args.id_column} = ?",
                (new, pk),
            )
            conn.commit()  # per-row commit
            updated += cur.rowcount

    finally:
        conn.close()
        print(f"\nDone. Updated {updated} rows. Skipped {skipped} rows.")
        if args.dry_run:
            print("(Dry run: no changes were written.)")


if __name__ == "__main__":
    main()
