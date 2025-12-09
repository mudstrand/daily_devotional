#!/usr/bin/env python3
import os
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from email.utils import parsedate_to_datetime

# DB path can come from ENV or CLI
DEFAULT_DB_PATH = os.getenv('DEVOTIONAL_DB', 'devotionals.sqlite3')


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def safe_parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse date_utc from formats like:
    - 'Thu, 01 Aug 2019 19:23:42 -0500' (RFC 2822/5322)
    - ISO-like strings
    Returns datetime or None if unparseable.
    """
    if not date_str:
        return None

    # RFC 2822/5322
    try:
        dt = parsedate_to_datetime(date_str)
        return dt
    except Exception:
        pass

    # ISO-ish
    try:
        cleaned = date_str.replace(' ', 'T') if ' ' in date_str and 'T' not in date_str else date_str
        cleaned = cleaned.rstrip('Z')
        return datetime.fromisoformat(cleaned)
    except Exception:
        pass

    return None


def yymm_from_dt(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return f'{dt.year % 100:02d}{dt.month:02d}'


def truthy(s: Optional[str]) -> bool:
    return bool(str(s).strip()) if s is not None else False


def row_to_export(row: sqlite3.Row) -> Dict[str, Any]:
    verse = row['verse']
    reflection = row['reflection']
    prayer = row['prayer']
    reading = row['reading']

    return {
        'message_id': row['message_id'],
        'date_utc': row['date_utc'],
        'subject': row['subject'],
        'verse': verse or '',
        'reflection': reflection or '',
        'prayer': prayer or '',
        'original_content': row['original_content'] or '',
        'found_verse': truthy(verse),
        'found_reflection': truthy(reflection),
        'found_prayer': truthy(prayer),
        'reading': reading or '',
        'found_reading': truthy(reading),
    }


def fetch_all_devotionals(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    with closing(conn.cursor()) as cur:
        cur.execute("""
            SELECT
                message_id, date_utc, subject, verse, reflection, prayer,
                reading, original_content, created_at, updated_at
            FROM devotionals
            ORDER BY date_utc ASC, created_at ASC
        """)
        return cur.fetchall()


def bucket_records(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group records by YYMM derived from date_utc. Records with unparseable/empty
    dates go into 'unknown'.
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        dt = safe_parse_date(rec.get('date_utc'))
        key = yymm_from_dt(dt) or 'unknown'
        buckets.setdefault(key, []).append(rec)
    return buckets


def write_buckets_flat(
    buckets: Dict[str, List[Dict[str, Any]]],
) -> List[Tuple[str, str, int]]:
    """
    Writes monthly arrays directly into the current directory:
      ./parsed_YYMM.json
    Unparseable dates go to:
      ./parsed_unknown.json
    """
    results: List[Tuple[str, str, int]] = []
    cwd = Path.cwd()

    for key, items in buckets.items():
        filename = f'parsed_{key}.json' if key != 'unknown' else 'parsed_unknown.json'
        out_path = cwd / filename
        with out_path.open('w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        results.append((key, str(out_path), len(items)))

    return results


def export_devotionals(db_path: str = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        rows = fetch_all_devotionals(conn)
        records = [row_to_export(r) for r in rows]
        buckets = bucket_records(records)
        results = write_buckets_flat(buckets)

    print('Export complete:')
    for key, path, count in sorted(results):
        print(f'* {key}: wrote {count:,} records to {path}')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Export devotionals to JSON grouped by YYMM (flat files in cwd).')
    parser.add_argument(
        '--db',
        default=DEFAULT_DB_PATH,
        help='Path to SQLite DB (default: env DEVOTIONAL_DB or devotionals.sqlite3)',
    )
    args = parser.parse_args()

    export_devotionals(db_path=args.db)
