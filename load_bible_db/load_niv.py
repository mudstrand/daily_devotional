#!/usr/bin/env python3
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ------------------- Config -------------------
API_BASE = os.getenv('BIBLE_API_BASE', 'http://localhost:8084')
DEFAULT_TRANSLATION = os.getenv('BIBLE_TRANSLATION', 'NIV')
DEFAULT_DB = os.getenv('BIBLE_VERSE_DB', 'bible_verse.db')
HTTP_TIMEOUT = float(os.getenv('BIBLE_HTTP_TIMEOUT', '20'))
DEFAULT_SLEEP = float(os.getenv('BIBLE_REQUEST_SLEEP', '0.05'))

# ------------------- DB schema (same as your ESV loader) -------------------
DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS verses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    verse INTEGER NOT NULL,
    translation TEXT NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(book, chapter, verse, translation)
);
CREATE INDEX IF NOT EXISTS idx_verses_book_chapter
ON verses (book, chapter, verse, translation);
"""

# ------------------- Reference parsing (same as your ESV loader) -------------------
BOOK = r'(?:[1-3]\s+)?[A-Za-z][A-Za-z ]+'
CH = r'\d+'
VER = r'\d+(?:[abc])?'
RANGE = rf'{VER}(?:-{VER})?'
LIST = rf'{RANGE}(?:,{RANGE})*'
REF_REGEX = re.compile(rf'^\s*({BOOK})\s+({CH}):({LIST})\s*$', re.IGNORECASE)
WHOLE_CH_REGEX = re.compile(rf'^\s*({BOOK})\s+({CH})\s*$', re.IGNORECASE)


def normalize_spacing(ref: str) -> str:
    s = ref.strip()
    s = re.sub(r'\s*:\s*', ':', s)
    s = re.sub(r'\s*,\s*', ',', s)
    s = re.sub(r'\s*-\s*', '-', s)
    s = re.sub(r'\s{2,}', ' ', s)
    return s


def strip_abc_suffixes(s: str) -> str:
    return re.sub(r'(\d)[abc]\b', r'\1', s, flags=re.IGNORECASE)


def parse_reference(ref: str) -> Optional[Tuple[str, int, str]]:
    s = normalize_spacing(ref)
    m = REF_REGEX.match(strip_abc_suffixes(s))
    if m:
        book = ' '.join(m.group(1).split())
        chapter = int(m.group(2))
        verses = m.group(3)
        return (book, chapter, verses)
    mch = WHOLE_CH_REGEX.match(ref.strip())
    if mch:
        book = ' '.join(mch.group(1).split())
        chapter = int(mch.group(2))
        return (book, chapter, '1-9999')
    return None


def expand_verse_list(verses: str) -> List[int]:
    out: List[int] = []
    for seg in verses.split(','):
        seg = seg.strip()
        if not seg:
            continue
        if '-' in seg:
            a, b = seg.split('-', 1)
            try:
                start = int(re.sub(r'[^\d]', '', a))
                end = int(re.sub(r'[^\d]', '', b))
            except Exception:
                continue
            if end < start:
                start, end = end, start
            out.extend(range(start, end + 1))
        else:
            v = int(re.sub(r'[^\d]', '', seg))
            out.append(v)
    return out


def load_references(path: Path) -> List[str]:
    refs: List[str] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        refs.append(s)
    return refs


# ------------------- Book lookup via /books -------------------
def http_get(url: str, params: Dict[str, str] | None = None) -> dict | list:
    if params:
        url = f'{url}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        data = resp.read().decode('utf-8', errors='replace')
        return json.loads(data)


def fetch_books() -> List[dict]:
    return http_get(f'{API_BASE}/books')


def normalize_book_key(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', s.lower())


def build_book_lookup() -> Dict[str, Tuple[int, str]]:
    books = fetch_books()
    lut: Dict[str, Tuple[int, str]] = {}
    for b in books:
        bid = int(b['id'])
        name = b['name']
        lut[normalize_book_key(name)] = (bid, name)
    # helpful aliases
    aliases = {
        'genesis': ['gen', 'gn'],
        'exodus': ['exo', 'ex'],
        'leviticus': ['lev', 'lv'],
        'numbers': ['num', 'nm'],
        'deuteronomy': ['deut', 'dt'],
        'joshua': ['jos', 'josh'],
        'judges': ['jdg', 'judg'],
        'ruth': ['rut', 'ru'],
        'psalms': ['ps', 'psa', 'psalm'],
        'proverbs': ['prov', 'pr'],
        'ecclesiastes': ['eccl', 'ecc'],
        'song of songs': ['song', 'sos', 'ss', 'songofsolomon'],
        'isaiah': ['isa'],
        'jeremiah': ['jer'],
        'lamentations': ['lam'],
        'ezekiel': ['ezek', 'eze'],
        'daniel': ['dan', 'dn'],
        'hosea': ['hos'],
        'joel': ['joe', 'jl'],
        'amos': ['am'],
        'obadiah': ['obad', 'ob'],
        'jonah': ['jon'],
        'micah': ['mic'],
        'nahum': ['nah'],
        'habakkuk': ['hab'],
        'zephaniah': ['zeph', 'zep'],
        'haggai': ['hag'],
        'zechariah': ['zech', 'zec'],
        'malachi': ['mal'],
        'matthew': ['matt', 'mt'],
        'mark': ['mk', 'mrk'],
        'luke': ['lk', 'luk'],
        'john': ['jn', 'jhn', 'joh'],
        'acts': ['act', 'ac'],
        'romans': ['rom', 'ro'],
        '1 corinthians': ['1 cor', '1cor'],
        '2 corinthians': ['2 cor', '2cor'],
        'galatians': ['gal'],
        'ephesians': ['eph'],
        'philippians': ['phil', 'php'],
        'colossians': ['col'],
        '1 thessalonians': ['1 thes', '1thes', '1thess', '1th'],
        '2 thessalonians': ['2 thes', '2thes', '2thess', '2th'],
        '1 timothy': ['1 tim', '1tim'],
        '2 timothy': ['2 tim', '2tim'],
        'titus': ['tit'],
        'philemon': ['phlm', 'phm'],
        'hebrews': ['heb'],
        'james': ['jas'],
        '1 peter': ['1 pe', '1 pet', '1ptr'],
        '2 peter': ['2 pe', '2 pet', '2ptr'],
        '1 john': ['1 jn', '1jhn'],
        '2 john': ['2 jn', '2jhn'],
        '3 john': ['3 jn', '3jhn'],
        'jude': ['jud'],
        'revelation': ['rev', 'apocalypse'],
    }
    for base, alist in aliases.items():
        kbase = normalize_book_key(base)
        if kbase in lut:
            for a in alist:
                lut.setdefault(normalize_book_key(a), lut[kbase])
    return lut


# ------------------- API fetch -------------------
def make_verse_id(book_id: int, chapter: int, verse: int) -> int:
    return int(f'{book_id:02d}{chapter:03d}{verse:03d}' if book_id < 100 else f'{book_id:03d}{chapter:03d}{verse:03d}')


def fetch_chapter(book_id: int, chapter: int, translation: str) -> List[dict]:
    url = f'{API_BASE}/books/{book_id}/chapters/{chapter}'
    return http_get(url, {'translation': translation})


def fetch_single_verse(book_id: int, chapter: int, verse: int, translation: str) -> dict:
    v_id = make_verse_id(book_id, chapter, verse)
    url = f'{API_BASE}/books/{book_id}/chapters/{chapter}/{v_id}'
    try:
        return http_get(url, {'translation': translation})
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # fallback to chapter filter
        arr = fetch_chapter(book_id, chapter, translation)
        for o in arr:
            if int(o.get('verseId')) == verse:
                return o
        raise


# ------------------- DB helpers -------------------
def ensure_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DB_SCHEMA)
    return conn


def verse_exists(conn: sqlite3.Connection, book: str, chapter: int, verse: int, translation: str) -> bool:
    cur = conn.execute(
        'SELECT 1 FROM verses WHERE book=? AND chapter=? AND verse=? AND translation=? LIMIT 1',
        (book, chapter, verse, translation),
    )
    return cur.fetchone() is not None


def save_verse(
    conn: sqlite3.Connection,
    book: str,
    chapter: int,
    verse: int,
    translation: str,
    text: str,
) -> None:
    conn.execute(
        'INSERT OR REPLACE INTO verses (book, chapter, verse, translation, text) VALUES (?,?,?,?,?)',
        (book, chapter, verse, translation, text),
    )


# ------------------- Core -------------------
def store_reference(
    conn: sqlite3.Connection,
    ref: str,
    translation: str,
    sleep_s: float,
    books_lut: Dict[str, Tuple[int, str]],
    preview: bool = False,
) -> None:
    parsed = parse_reference(ref)
    if not parsed:
        print(f'[WARN] Skipping unparsable reference: {ref}', file=sys.stderr)
        return

    book, chapter, verses = parsed

    # whole chapter -> fetch once, iterate verseId order
    if verses == '1-9999':
        k = normalize_book_key(book)
        if k not in books_lut:
            print(f'[WARN] Unknown book in whole-chapter line: {ref}', file=sys.stderr)
            return
        book_id, canonical = books_lut[k]
        arr = fetch_chapter(book_id, chapter, translation)
        arr_sorted = sorted(arr, key=lambda o: int(o.get('verseId', 0)))
        for obj in arr_sorted:
            v = int(obj.get('verseId'))
            t = (obj.get('verse') or obj.get('text') or '').strip()
            if not t:
                continue
            if verse_exists(conn, canonical, chapter, v, translation):
                continue
            if preview:
                print(
                    f'[PREVIEW] INSERT verses(book,chapter,verse,translation,text) '
                    f'VALUES ({canonical!r},{chapter},{v},{translation!r},{t!r})'
                )
            else:
                save_verse(conn, canonical, chapter, v, translation, t)
                if sleep_s > 0:
                    time.sleep(sleep_s)
        if not preview:
            conn.commit()
        return

    # explicit list of verses
    k = normalize_book_key(book)
    if k not in books_lut:
        print(f'[WARN] Unknown book: {book}', file=sys.stderr)
        return
    book_id, canonical = books_lut[k]
    for v in expand_verse_list(verses):
        if verse_exists(conn, canonical, chapter, v, translation):
            continue
        obj = fetch_single_verse(book_id, chapter, v, translation)
        t = (obj.get('verse') or obj.get('text') or '').strip()
        if not t:
            print(f'[WARN] Empty text for {canonical} {chapter}:{v}', file=sys.stderr)
            continue
        if preview:
            print(
                f'[PREVIEW] INSERT verses(book,chapter,verse,translation,text) '
                f'VALUES ({canonical!r},{chapter},{v},{translation!r},{t!r})'
            )
        else:
            save_verse(conn, canonical, chapter, v, translation, t)
            if sleep_s > 0:
                time.sleep(sleep_s)
    if not preview:
        conn.commit()


# ------------------- CLI -------------------
def main():
    parser = argparse.ArgumentParser(
        description='Fetch NIV (local Bible Go API) verses for references and store into SQLite using existing schema.'
    )
    parser.add_argument('refs_file', help='Text file with one Bible reference per line')
    parser.add_argument(
        '--db',
        default=DEFAULT_DB,
        help='SQLite DB file (default: env BIBLE_VERSE_DB or bible_verse.db)',
    )
    parser.add_argument(
        '--translation',
        default=DEFAULT_TRANSLATION,
        help=f'Translation code to store (default: {DEFAULT_TRANSLATION})',
    )
    parser.add_argument(
        '--sleep',
        type=float,
        default=DEFAULT_SLEEP,
        help=f'Sleep between API requests (default: {DEFAULT_SLEEP}s)',
    )
    parser.add_argument(
        '--preview',
        action='store_true',
        help='Print would-be inserts without writing to DB',
    )
    args = parser.parse_args()

    refs_path = Path(args.refs_file)
    if not refs_path.exists():
        print(f'[ERROR] {refs_path} not found', file=sys.stderr)
        sys.exit(2)

    try:
        books_lut = build_book_lookup()
    except Exception as e:
        print(f'[ERROR] Failed to fetch /books from {API_BASE}: {e}', file=sys.stderr)
        sys.exit(2)

    conn = ensure_db(Path(args.db))
    refs = load_references(refs_path)
    print(f'[INFO] Loaded {len(refs)} references from {refs_path}')
    print(f'[INFO] Using API base={API_BASE}, translation={args.translation}, preview={args.preview}')

    for i, ref in enumerate(refs, start=1):
        try:
            store_reference(conn, ref, args.translation, args.sleep, books_lut, preview=args.preview)
        except Exception as e:
            print(f'[ERROR] {ref}: {e}', file=sys.stderr)
        if i % 50 == 0:
            print(f'[INFO] Processed {i}/{len(refs)}')

    if args.preview:
        print('[PREVIEW DONE]')
    else:
        print('[DONE]')


if __name__ == '__main__':
    main()
