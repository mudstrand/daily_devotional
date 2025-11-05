#!/usr/bin/env python3
import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.parse
import urllib.request

API_BASE = "https://bible-api.com"
TRANSLATION = "asv"
USER_AGENT = "VerseFetcher/1.1 (+https://example.local)"

REF_SPLIT_RE = re.compile(r"\s*,\s*")
PART_SUFFIX_RE = re.compile(r"([0-9]+)([abc])$", re.IGNORECASE)
BOOK_CHAPTER_RE = re.compile(
    r"^\s*(?P<book>[\dA-Za-z ]+?)\s+(?P<chapter>\d+):(?P<rest>.+?)\s*$"
)

DB_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_ref TEXT NOT NULL,
    normalized_ref TEXT NOT NULL,
    translation TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_request
ON responses (normalized_ref, translation);
CREATE INDEX IF NOT EXISTS idx_original_ref
ON responses (original_ref);
"""


def http_get_json(url: str, timeout: float = 20.0) -> Tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            return status, body
    except Exception as e:
        raise RuntimeError(f"HTTP error for {url}: {e}")


def strip_part_suffix(token: str) -> str:
    m = PART_SUFFIX_RE.search(token.strip())
    if m:
        return m.group(1)
    return token.strip()


def normalize_single_reference(ref_line: str) -> str:
    """
    Normalize to bible-api.com format; raises ValueError on parse issues.
    """
    if ref_line is None:
        raise ValueError("Reference is None")
    s = ref_line.strip().strip('"').strip("'").strip()
    if not s:
        raise ValueError("Reference is empty")

    m = BOOK_CHAPTER_RE.match(s)
    if not m:
        raise ValueError(f"Cannot parse book/chapter/verses from: {ref_line!r}")

    book = " ".join(m.group("book").split())
    chapter = m.group("chapter")
    rest = m.group("rest").strip()

    if not rest:
        raise ValueError(f"No verse component after chapter in: {ref_line!r}")

    parts = REF_SPLIT_RE.split(rest)
    if not parts:
        raise ValueError(f"No verse parts detected in: {ref_line!r}")

    cleaned_parts: List[str] = []
    for part in parts:
        p = part.strip()
        if not p:
            continue
        if "-" in p:
            if p.count("-") != 1:
                raise ValueError(
                    f"Invalid range (multiple hyphens) in: {ref_line!r} part={p!r}"
                )
            a, b = p.split("-", 1)
            a_clean = strip_part_suffix(a)
            b_clean = strip_part_suffix(b)
            if not a_clean.isdigit() or not b_clean.isdigit():
                raise ValueError(
                    f"Range endpoints must be numeric in: {ref_line!r} part={p!r}"
                )
            if int(a_clean) > int(b_clean):
                raise ValueError(f"Range start > end in: {ref_line!r} part={p!r}")
            cleaned_parts.append(f"{a_clean}-{b_clean}")
        else:
            v = strip_part_suffix(p)
            if not v.isdigit():
                raise ValueError(
                    f"Verse number must be numeric in: {ref_line!r} part={p!r}"
                )
            cleaned_parts.append(v)

    if not cleaned_parts:
        raise ValueError(f"No usable verse parts after normalization in: {ref_line!r}")

    normalized = f"{book} {chapter}:{','.join(cleaned_parts)}"
    return normalized


def build_api_url(normalized_ref: str) -> str:
    q = urllib.parse.quote(normalized_ref)
    return f"{API_BASE}/{q}?translation={TRANSLATION}"


def ensure_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DB_SCHEMA)
    return conn


def save_response(
    conn: sqlite3.Connection,
    original_ref: str,
    normalized_ref: str,
    status: int,
    body: str,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO responses (original_ref, normalized_ref, translation, status_code, response_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (original_ref, normalized_ref, TRANSLATION, status, body, int(time.time())),
    )
    conn.commit()


def already_cached(conn: sqlite3.Connection, normalized_ref: str) -> Optional[Dict]:
    cur = conn.execute(
        "SELECT status_code, response_json FROM responses WHERE normalized_ref=? AND translation=?",
        (normalized_ref, TRANSLATION),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {"status": row[0], "json": row[1]}


def validate_api_json(status: int, body: str, url: str, ref: str) -> None:
    """
    Raise RuntimeError if the response is invalid or indicates an error.
    """
    if status != 200:
        snippet = (body or "")[:300]
        raise RuntimeError(
            f"Non-200 response for {ref} ({url}): HTTP {status}; body: {snippet}"
        )

    try:
        data = json.loads(body)
    except Exception as e:
        raise RuntimeError(
            f"Invalid JSON for {ref} ({url}): {e}; body excerpt: {(body or '')[:200]}"
        )

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Unexpected JSON type for {ref} ({url}): expected object, got {type(data).__name__}"
        )

    # bible-api.com typical success has 'verses'
    if (
        "verses" not in data
        or not isinstance(data["verses"], list)
        or not data["verses"]
    ):
        raise RuntimeError(
            f"JSON missing 'verses' array or empty for {ref} ({url}); body excerpt: {(body or '')[:200]}"
        )


def fetch_and_cache(
    conn: sqlite3.Connection,
    original_ref: str,
    sleep_seconds: float = 0.5,
    force: bool = False,
    dry_run: bool = False,
) -> Tuple[str, Optional[int], Optional[str]]:
    """
    Fail-fast: raises on any error with detailed context.
    Returns (normalized_ref, status, response_json) on success.
    """
    normalized = normalize_single_reference(original_ref)
    url = build_api_url(normalized)

    if dry_run:
        return normalized, None, None

    if not force:
        cached = already_cached(conn, normalized)
        if cached:
            # Validate cached success minimally (don’t raise for historical non-200; you can --force to refresh)
            return normalized, cached["status"], cached["json"]

    status, body = http_get_json(url)
    validate_api_json(status, body, url, original_ref)

    save_response(conn, original_ref.strip(), normalized, status, body)

    # Optional pacing for public API politeness
    if sleep_seconds and sleep_seconds > 0:
        time.sleep(sleep_seconds)

    return normalized, status, body


def query_cached(conn: sqlite3.Connection, input_ref: str) -> List[Dict]:
    normalized = normalize_single_reference(input_ref)
    cur = conn.execute(
        "SELECT original_ref, normalized_ref, translation, status_code, response_json, created_at FROM responses WHERE normalized_ref=? AND translation=?",
        (normalized, TRANSLATION),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_references_from_text(path: Path) -> List[str]:
    refs: List[str] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        refs.append(s)
    return refs


def main():
    parser = argparse.ArgumentParser(
        description="Fetch ASV verses from bible-api.com (fail-fast with precise error logging)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser(
        "fetch", help="Fetch all references from a text file (one per line)."
    )
    p_fetch.add_argument("input_file", help="Text file with one reference per line")
    p_fetch.add_argument(
        "--db",
        default="bible_cache.sqlite",
        help="SQLite DB path (default: bible_cache.sqlite)",
    )
    p_fetch.add_argument(
        "--sleep", type=float, default=0.5, help="Delay between requests (seconds)"
    )
    p_fetch.add_argument(
        "--force", action="store_true", help="Force re-fetch even if cached"
    )
    p_fetch.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fetched without HTTP calls",
    )
    p_fetch.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Do not stop on first error; log and continue",
    )

    p_query = sub.add_parser("query", help="Query cached responses for a reference")
    p_query.add_argument(
        "reference",
        help='Reference to query (e.g., "John 3:16", "Psalm 66:17, 18, 19a")',
    )
    p_query.add_argument("--db", default="bible_cache.sqlite", help="SQLite DB path")

    p_export = sub.add_parser("export", help="Export cached results to JSON or CSV")
    p_export.add_argument("--db", default="bible_cache.sqlite", help="SQLite DB path")
    p_export.add_argument("--format", choices=["json", "csv"], default="json")
    p_export.add_argument("--out", default="export.json", help="Output file")

    args = parser.parse_args()

    db_path = Path(args.db if hasattr(args, "db") else "bible_cache.sqlite")
    conn = ensure_db(db_path)

    if args.cmd == "fetch":
        refs = load_references_from_text(Path(args.input_file))
        print(f"Loaded {len(refs)} references from {args.input_file}")

        for i, ref in enumerate(refs, start=1):
            try:
                normalized, status, body = fetch_and_cache(
                    conn,
                    original_ref=ref,
                    sleep_seconds=args.sleep,
                    force=args.force,
                    dry_run=args.dry_run,
                )
                if args.dry_run:
                    print(f"[{i}/{len(refs)}][DRY] Would fetch: {normalized} (ASV)")
                else:
                    print(
                        f"[{i}/{len(refs)}] OK: {ref} -> {normalized} (status {status})"
                    )
            except (ValueError, RuntimeError) as e:
                print(f"[{i}/{len(refs)}] ERROR for {ref!r}: {e}")
                if not args.continue_on_error:
                    sys.exit(2)
                # otherwise continue to next

        print("Done.")

    elif args.cmd == "query":
        try:
            rows = query_cached(conn, args.reference)
        except ValueError as e:
            print(f"[QUERY ERROR] {e}")
            sys.exit(3)

        if not rows:
            print("No cached entry for that reference.")
            sys.exit(1)

        for row in rows:
            print(f"- original: {row['original_ref']}")
            print(f"  normalized: {row['normalized_ref']}")
            print(f"  translation: {row['translation']}")
            print(f"  status: {row['status_code']}")
            try:
                data = json.loads(row["response_json"])
                if isinstance(data, dict) and "verses" in data:
                    verse_text = " ".join(
                        v.get("text", "").strip() for v in data["verses"]
                    )
                    print(f"  verses: {len(data['verses'])}")
                    print(
                        f"  text: {verse_text[:200]}{' …' if len(verse_text) > 200 else ''}"
                    )
                else:
                    print(
                        f"  json: {row['response_json'][:200]}{' …' if len(row['response_json']) > 200 else ''}"
                    )
            except Exception:
                print(
                    f"  json: {row['response_json'][:200]}{' …' if len(row['response_json']) > 200 else ''}"
                )

    elif args.cmd == "export":
        cur = conn.execute(
            "SELECT original_ref, normalized_ref, translation, status_code, response_json, created_at FROM responses ORDER BY id ASC"
        )
        rows = cur.fetchall()
        if args.format == "json":
            out = [
                {
                    "original_ref": r[0],
                    "normalized_ref": r[1],
                    "translation": r[2],
                    "status_code": r[3],
                    "response": json.loads(r[4]) if r[4] else None,
                    "created_at": r[5],
                }
                for r in rows
            ]
            Path(args.out).write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"Wrote {len(out)} records to {args.out}")
        else:
            with open(args.out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(
                    [
                        "original_ref",
                        "normalized_ref",
                        "translation",
                        "status_code",
                        "response_json",
                        "created_at",
                    ]
                )
                for r in rows:
                    w.writerow(r)
            print(f"Wrote {len(rows)} rows to {args.out}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
