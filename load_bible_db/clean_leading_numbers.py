#!/usr/bin/env python3
import argparse
import os
import re
import sqlite3
import sys
from textwrap import shorten

# Matches a leading “[ 123 ] ” (with optional spaces) at the very start
LEADING_BRACKETED_NUM = re.compile(r'^\s*\[\s*\d+\s*\]\s*')


def open_db() -> sqlite3.Connection:
    db_path = os.getenv('BIBLE_VERSE_DB')
    if not db_path:
        print('ERROR: BIBLE_VERSE_DB environment variable is not set.', file=sys.stderr)
        sys.exit(2)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def list_missing(conn: sqlite3.Connection, limit: int) -> int:
    """
    List verses that do NOT start with a leading [nn].
    Returns the total count of such verses.
    """
    cur = conn.execute('SELECT id, book, chapter, verse, translation, text FROM verses')
    missing = []
    for r in cur:
        text = r['text'] or ''
        if not LEADING_BRACKETED_NUM.match(text):
            missing.append(r)

    total = len(missing)
    print(f'Verses WITHOUT leading [nn]: {total}')
    if total == 0:
        return 0

    print(f'\nSample (up to {limit} rows):')
    for r in missing[:limit]:
        ref = f'{r["book"]} {r["chapter"]}:{r["verse"]} ({r["translation"]})'
        txt = r['text'] or ''
        print(f'- {ref}')
        print(f'  TEXT: {shorten(txt, width=200, placeholder="…")!r}')
    return total


def preview_removals(conn: sqlite3.Connection, limit: int) -> int:
    """
    Show rows that START with [nn] and the proposed cleaned text.
    Returns the total count of such rows.
    """
    cur = conn.execute('SELECT id, book, chapter, verse, translation, text FROM verses')
    candidates = []
    for r in cur:
        text = r['text'] or ''
        if LEADING_BRACKETED_NUM.match(text):
            candidates.append(r)

    total = len(candidates)
    print(f'Rows starting with a bracketed number: {total}')
    if total == 0:
        return 0

    print(f'\nSample preview (up to {limit} rows):')
    for r in candidates[:limit]:
        old = r['text'] or ''
        new = LEADING_BRACKETED_NUM.sub('', old).lstrip()
        ref = f'{r["book"]} {r["chapter"]}:{r["verse"]} ({r["translation"]})'
        print(f'- {ref}')
        print(f'  OLD: {shorten(old, width=200, placeholder="…")!r}')
        print(f'  NEW: {shorten(new, width=200, placeholder="…")!r}')
    return total


def apply_removals(conn: sqlite3.Connection) -> int:
    """
    Remove the leading [nn] from all rows that have it. Returns the number of updated rows.
    """
    cur = conn.execute('SELECT id, text FROM verses')
    to_update = []
    for r in cur:
        old = r['text'] or ''
        if LEADING_BRACKETED_NUM.match(old):
            new = LEADING_BRACKETED_NUM.sub('', old).lstrip()
            if new != old:
                to_update.append((new, r['id']))

    if not to_update:
        return 0

    conn.execute('BEGIN')
    for new, rid in to_update:
        conn.execute('UPDATE verses SET text=? WHERE id=?', (new, rid))
    conn.commit()
    return len(to_update)


def main():
    parser = argparse.ArgumentParser(description='Clean or inspect leading [nn] prefixes in the verses table.')
    parser.add_argument(
        '--preview',
        action='store_true',
        help='Show proposed changes for rows starting with [nn] (no DB writes)',
    )
    parser.add_argument(
        '--list-missing',
        action='store_true',
        help='List verses that DO NOT start with [nn] (no DB writes)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=20,
        help='Number of sample rows to display (default: 20)',
    )
    args = parser.parse_args()

    conn = open_db()
    try:
        if args.list_missing:
            total = list_missing(conn, args.limit)
            print('\n--list-missing: no changes written.')
            return

        total = preview_removals(conn, args.limit)

        if args.preview or total == 0:
            print('\n--preview: no changes written.')
            return

        ans = input("\nProceed to remove leading [nn] from these rows? Type 'yes' to continue: ").strip().lower()
        if ans != 'yes':
            print('Aborted. No changes made.')
            return

        updated = apply_removals(conn)
        print(f'Updated {updated} rows.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
