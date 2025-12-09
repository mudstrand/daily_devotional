#!/usr/bin/env python3
import sys
import json
import sqlite3
import glob
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Iterable, Optional

TABLE_NAME = 'devotionals'

# Database column order (first seven explicitly ordered, rest follow)
COLUMNS = [
    'message_id',
    'msg_date',
    'subject',
    'verse',
    'reading',
    'reflection',
    'holiday',  # NEW: directly after reflection
    # remaining fields (any order after the first seven)
    'ai_prayer',
    'ai_reading',
    'ai_reflection_corrected',
    'ai_subject',
    'ai_verse',
    'date_utc',
    'original_content',
    'orignal_subject',  # intentional spelling per spec
    'prayer',
    'verse_source',
    'verse_text',
]

DB_PATH = '/Users/mark/shared/daily_devotional_v2.db'

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    message_id TEXT PRIMARY KEY,
    msg_date TEXT,               -- YYYY-MM-DD (derived from date_utc if absent)
    subject TEXT,
    verse TEXT,
    reading TEXT,
    reflection TEXT,
    holiday TEXT,                -- enum string or NULL (e.g., 'easter', 'thanksgiving')
    ai_prayer TEXT,
    ai_reading TEXT,
    ai_reflection_corrected TEXT,
    ai_subject TEXT,
    ai_verse TEXT,
    date_utc TEXT,
    original_content TEXT,
    orignal_subject TEXT,
    prayer TEXT,
    verse_source TEXT,
    verse_text TEXT
);
"""

INSERT_SQL = f"""
INSERT INTO {TABLE_NAME} ({', '.join(COLUMNS)})
VALUES ({', '.join(['?'] * len(COLUMNS))});
"""


def connect_sqlite(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # Ensure NOT WAL mode: single main .db file (a transient -journal may appear during transactions)
    conn.execute('PRAGMA journal_mode=DELETE;')
    # Strong durability for shared/network drives
    conn.execute('PRAGMA synchronous=FULL;')
    conn.execute('PRAGMA foreign_keys=ON;')
    return conn


def parse_iso_ymd_from_date_utc(value: Any) -> Optional[str]:
    """
    Parse many UTC/date-time formats and return YYYY-MM-DD.
    Accepts:
      - ISO-8601 with/without Z or offset (e.g., '2021-10-22T21:24:26+00:00', '2021-10-22T21:24:26Z')
      - RFC 2822 (e.g., 'Tue, 16 Jul 2019 19:05:51 -0500')
      - Common 'YYYY-MM-DD[ HH:MM[:SS]]' formats
    Fallback: first 10 chars if they validate as YYYY-MM-DD.
    """
    from email.utils import parsedate_to_datetime

    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Fast path if the prefix is already YYYY-MM-DD
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        ymd = s[:10]
        try:
            datetime.strptime(ymd, '%Y-%m-%d')
            return ymd
        except Exception:
            pass

    # ISO 8601 attempts (stdlib only)
    ss = s.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(ss)
        return dt.date().isoformat()
    except Exception:
        # Try space-to-T
        if ' ' in ss and 'T' not in ss:
            try:
                dt = datetime.fromisoformat(ss.replace(' ', 'T'))
                return dt.date().isoformat()
            except Exception:
                pass

    # RFC 2822 (email-style)
    try:
        dt = parsedate_to_datetime(s)
        return dt.date().isoformat()
    except Exception:
        pass

    # Common patterns without offsets
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S'):
        try:
            dt = datetime.strptime(s[: len(fmt)], fmt)
            return dt.date().isoformat()
        except Exception:
            continue

    # Final fallback: trust first 10 chars if they validate
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        ymd = s[:10]
        try:
            datetime.strptime(ymd, '%Y-%m-%d')
            return ymd
        except Exception:
            pass

    return None


def load_json_records(path: Path) -> List[Dict[str, Any]]:
    with path.open('r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def project_record(rec: Dict[str, Any]) -> List[Any]:
    """
    Ensure msg_date is present (derive from date_utc if missing).
    Return values aligned with COLUMNS.
    """
    out = dict(rec)  # shallow copy

    # msg_date
    if not out.get('msg_date'):
        msg_date = parse_iso_ymd_from_date_utc(out.get('date_utc'))
        if msg_date:
            out['msg_date'] = msg_date
        else:
            out.setdefault('msg_date', None)

    # Canonical prominent fields
    out.setdefault('subject', out.get('subject'))
    out.setdefault('verse', out.get('verse'))
    out.setdefault('reading', out.get('reading'))
    out.setdefault(
        'reflection',
        out.get('reflection') or out.get('ai_reflection_corrected') or out.get('original_content'),
    )

    # holiday: pass through if present; else None
    out.setdefault('holiday', out.get('holiday', None))

    return [out.get(col) for col in COLUMNS]


def iter_input_files(patterns: Iterable[str]) -> List[Path]:
    files: List[str] = []
    for pat in patterns:
        files.extend(glob.glob(pat, recursive=True))
    paths: List[Path] = []
    seen = set()
    for f in files:
        p = Path(f)
        if p.suffix.lower() == '.json' and p.is_file():
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                paths.append(p)
    return paths


def main(argv: List[str]) -> None:
    if len(argv) < 2:
        print('Usage: python load_json_to_sqlite.py <glob1> [<glob2> ...]')
        print("Example: python load_json_to_sqlite.py './data/*.json' 'more/**/*.json'")
        sys.exit(2)

    patterns = argv[1:]
    files = iter_input_files(patterns)
    if not files:
        print('No JSON files matched the given patterns.')
        sys.exit(1)

    conn = connect_sqlite(DB_PATH)
    try:
        with conn:
            conn.execute(CREATE_TABLE_SQL)

        with conn:
            cur = conn.cursor()
            total_rows = 0
            for jf in files:
                try:
                    records = load_json_records(jf)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f'Invalid JSON in file {jf}: {e}') from e

                for rec in records:
                    if not rec.get('message_id'):
                        raise RuntimeError(f'Missing message_id in file {jf}')

                    params = project_record(rec)
                    cur.execute(INSERT_SQL, params)
                    total_rows += 1

        print(f'Completed. Files processed: {len(files)}, rows inserted: {total_rows}')

    except sqlite3.IntegrityError as e:
        # PK conflict or other constraint issue: abort everything
        print(f'ERROR: Integrity constraint violated: {e}')
        print('All changes have been rolled back. No rows were inserted.')
        sys.exit(1)
    except Exception as e:
        print(f'ERROR: {e}')
        print('All changes have been rolled back.')
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main(sys.argv)
