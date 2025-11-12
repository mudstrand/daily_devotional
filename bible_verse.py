#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
import sys
import os

BIBLE_VERSE_DB = os.getenv("BIBLE_VERSE_DB")
TABLE_VERSES = "verses"  # change if your table name differs


@dataclass(frozen=True)
class VerseQuery:
    book: str
    chapter: int
    start_verse: int
    end_verse: Optional[int]  # inclusive if provided
    translation: str


def connect_sqlite(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=DELETE;")
    conn.execute("PRAGMA synchronous=FULL;")
    return conn


# ---------------- Parsing ----------------
_SINGLE_OR_RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$")


def parse_single_or_range(spec: str) -> Tuple[int, Optional[int]]:
    """
    Accepts '10' or '10-13' (whitespace allowed around '-') and returns (start, end_or_none).
    """
    m = _SINGLE_OR_RANGE_RE.fullmatch(spec)
    if not m:
        raise ValueError(f"Invalid verse specification segment: {spec!r}")
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else None
    if end is not None and end < start:
        raise ValueError(f"Verse range end < start: {spec!r}")
    return start, end


def split_comma_list(verse_spec: str) -> List[str]:
    """
    Split a verse_spec like '1-3,5,7-9' into ['1-3','5','7-9'].
    Allows arbitrary spaces around commas and hyphens.
    """
    parts = [p.strip() for p in verse_spec.split(",")]
    return [p for p in parts if p]


# ---------------- DB access ----------------
def _select_rows(conn: sqlite3.Connection, q: VerseQuery) -> List[sqlite3.Row]:
    """
    Fetch verse rows in order (by verse asc). Requires exact book, chapter, translation match.
    """
    if q.end_verse is None:
        sql = f"""
            SELECT * FROM {TABLE_VERSES}
            WHERE book = ? AND chapter = ? AND translation = ? AND verse = ?
            ORDER BY verse ASC
        """
        params = (q.book, q.chapter, q.translation, q.start_verse)
    else:
        sql = f"""
            SELECT * FROM {TABLE_VERSES}
            WHERE book = ? AND chapter = ? AND translation = ?
              AND verse BETWEEN ? AND ?
            ORDER BY verse ASC
        """
        params = (q.book, q.chapter, q.translation, q.start_verse, q.end_verse)
    return list(conn.execute(sql, params).fetchall())


# ---------------- Text assembly ----------------
def _strip_square_refs(text: str) -> str:
    """
    Remove [n] markers like '[5] '.
    """
    return re.sub(r"\[(\d+)\]\s*", "", text)


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", s).strip()


def _looks_like_has_refs(s: str) -> bool:
    # Heuristic: presence of [number] suggests refs are embedded already
    return bool(re.search(r"\[\d+\]", s))


def assemble_text(
    rows: Sequence[sqlite3.Row],
    include_refs: bool = True,
    add_refs_if_missing: bool = True,
    sep: str = " ",
) -> Optional[str]:
    """
    Concatenate text from rows in order.
    - If include_refs=False: remove any embedded [n] markers and join clean text.
    - If include_refs=True:
        * If combined text already contains [n], return as-is (normalized spacing).
        * Else, if add_refs_if_missing=True, decorate each verse as "[n] text".
        * Else, return plain concatenation without markers.
    """
    if not rows:
        return None

    pieces: List[str] = []
    for r in rows:
        t = (r["text"] or "").strip()
        pieces.append(t)
    combined = _normalize_whitespace(sep.join(pieces))

    if not include_refs:
        stripped_parts = [_strip_square_refs(p) for p in pieces]
        return _normalize_whitespace(sep.join(stripped_parts))

    if _looks_like_has_refs(combined):
        return combined

    if not add_refs_if_missing:
        return combined

    decorated: List[str] = []
    for r in rows:
        vnum = int(r["verse"])
        t = (r["text"] or "").strip()
        t_clean = _strip_square_refs(t)
        decorated.append(f"[{vnum}] {t_clean}")
    return _normalize_whitespace(sep.join(decorated))


# ---------------- Public API ----------------
def get_verse_text(
    book: str,
    chapter: int,
    verse_spec: str,
    translation: str,
    db_path: Path = BIBLE_VERSE_DB,
    include_refs: bool = True,
    add_refs_if_missing: bool = True,
    sep: str = " ",
) -> Optional[str]:
    """
    Look up and assemble verse text for:
    - book: e.g., 'John' or '1 John'
    - chapter: integer
    - verse_spec: '10', '10-13', or comma list like '1-3,5,7-9'
    - translation: e.g., 'ESV', 'NIV'
    Behavior:
      * include_refs=False: returns plain text without [n] markers.
      * include_refs=True: preserves [n] if present in source; if missing and
        add_refs_if_missing=True, inserts "[n] " before each verse (useful for NIV).
      * For comma lists, concatenates each segment's result separated by a single space.
    """
    segments = split_comma_list(verse_spec)
    if not segments:
        raise ValueError("verse_spec must contain at least one verse or range")

    texts: List[str] = []
    with connect_sqlite(db_path) as conn:
        for seg in segments:
            start, end = parse_single_or_range(seg)
            q = VerseQuery(
                book=book,
                chapter=chapter,
                start_verse=start,
                end_verse=end,
                translation=translation,
            )
            rows = _select_rows(conn, q)
            part = assemble_text(
                rows,
                include_refs=include_refs,
                add_refs_if_missing=add_refs_if_missing,
                sep=sep,
            )
            if part:
                texts.append(part)

    if not texts:
        return None
    return _normalize_whitespace(" ".join(texts))


# ---------------- CLI for quick testing ----------------
def _cli():
    ap = argparse.ArgumentParser(description="Fetch verse text from bible_verse.db")
    ap.add_argument("--db", default=str(BIBLE_VERSE_DB), help="Path to bible_verse.db")
    ap.add_argument("--book", required=True, help="Book name, e.g., 'John' or '1 John'")
    ap.add_argument(
        "--chapter", required=True, type=int, help="Chapter number, e.g., 15"
    )
    ap.add_argument(
        "--verse",
        required=True,
        help="Verse/range or comma list, e.g., '5', '5-11', '1,3-4'",
    )
    ap.add_argument(
        "--translation", required=True, help="Translation code, e.g., ESV, NIV"
    )
    ap.add_argument(
        "--no-refs",
        action="store_true",
        help="Strip or omit [n] verse markers from output",
    )
    ap.add_argument(
        "--no-autodecorate",
        action="store_true",
        help="Do not add [n] markers if missing",
    )
    args = ap.parse_args()

    text = get_verse_text(
        book=args.book,
        chapter=args.chapter,
        verse_spec=args.verse,
        translation=args.translation,
        db_path=Path(args.db),
        include_refs=not args.no_refs,
        add_refs_if_missing=not args.no_autodecorate,
    )

    if text is None:
        print("Not found")
        sys.exit(1)
    print(text)


if __name__ == "__main__":
    _cli()
