# bible_verse.py
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import select
from db_bible import engine
from models import verses


@dataclass(frozen=True)
class VerseQuery:
    book: str
    chapter: int
    start_verse: int
    end_verse: Optional[int]
    translation: str


_SINGLE_OR_RANGE_RE = re.compile(r'^\s*(\d+)\s*(?:-\s*(\d+))?\s*$')


def parse_single_or_range(spec: str) -> Tuple[int, Optional[int]]:
    m = _SINGLE_OR_RANGE_RE.fullmatch(spec)
    if not m:
        raise ValueError(f'Invalid verse specification segment: {spec!r}')
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else None
    if end is not None and end < start:
        raise ValueError(f'Verse range end < start: {spec!r}')
    return start, end


def split_comma_list(verse_spec: str) -> List[str]:
    parts = [p.strip() for p in verse_spec.split(',')]
    return [p for p in parts if p]


def _select_rows(conn, q: VerseQuery) -> List[dict]:
    stmt = (
        select(verses)
        .where(
            verses.c.book == q.book,
            verses.c.chapter == q.chapter,
            verses.c.translation == q.translation,
        )
        .order_by(verses.c.verse.asc())
    )
    if q.end_verse is None:
        stmt = stmt.where(verses.c.verse == q.start_verse)
    else:
        stmt = stmt.where(verses.c.verse.between(q.start_verse, q.end_verse))
    res = conn.execute(stmt).mappings().all()
    return [dict(r) for r in res]


def _strip_square_refs(text: str) -> str:
    return re.sub(r'\[(\d+)\]\s*', '', text)


def _normalize_whitespace(s: str) -> str:
    return re.sub(r'[ \t\r\f\v]+', ' ', s).strip()


def _looks_like_has_refs(s: str) -> bool:
    return bool(re.search(r'\[\d+\]', s))


def assemble_text(
    rows: Sequence[dict],
    include_refs: bool = True,
    add_refs_if_missing: bool = True,
    sep: str = ' ',
) -> Optional[str]:
    if not rows:
        return None
    pieces: List[str] = [(r.get('text') or '').strip() for r in rows]
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
        vnum = int(r['verse'])
        t_clean = _strip_square_refs((r.get('text') or '').strip())
        decorated.append(f'[{vnum}] {t_clean}')
    return _normalize_whitespace(sep.join(decorated))


def get_verse_text(
    book: str,
    chapter: int,
    verse_spec: str,
    translation: str,
    include_refs: bool = True,
    add_refs_if_missing: bool = True,
    sep: str = ' ',
) -> Optional[str]:
    segments = split_comma_list(verse_spec)
    if not segments:
        raise ValueError('verse_spec must contain at least one verse or range')
    texts: List[str] = []
    with engine.begin() as conn:
        for seg in segments:
            start, end = parse_single_or_range(seg)
            q = VerseQuery(book, chapter, start, end, translation)
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
    return _normalize_whitespace(' '.join(texts))


def _cli():
    ap = argparse.ArgumentParser(description='Fetch verse text via SQLAlchemy (Postgres)')
    ap.add_argument('--book', required=True)
    ap.add_argument('--chapter', required=True, type=int)
    ap.add_argument('--verse', required=True)
    ap.add_argument('--translation', required=True)
    ap.add_argument('--no-refs', action='store_true')
    ap.add_argument('--no-autodecorate', action='store_true')
    args = ap.parse_args()

    text = get_verse_text(
        book=args.book,
        chapter=args.chapter,
        verse_spec=args.verse,
        translation=args.translation,
        include_refs=not args.no_refs,
        add_refs_if_missing=not args.no_autodecorate,
    )
    if text is None:
        print('Not found')
        sys.exit(1)
    print(text)


if __name__ == '__main__':
    _cli()
