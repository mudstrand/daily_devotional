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

ESV_BASE = "https://api.esv.org/v3/passage/text/"
# We’ll ask ESV for text with verse numbers and minimal extras, then isolate each verse:
# However, ESV passage/text returns blocks; we’ll request one-verse increments per segment to be reliable.

BOOK = r"(?:[1-3]\s+)?[A-Za-z][A-Za-z ]+"
CH = r"\d+"
VER = r"\d+(?:[abc])?"
RANGE = rf"{VER}(?:-{VER})?"
LIST = rf"{RANGE}(?:,{RANGE})*"
REF_REGEX = re.compile(rf"^\s*({BOOK})\s+({CH}):({LIST})\s*$", re.IGNORECASE)
WHOLE_CH_REGEX = re.compile(rf"^\s*({BOOK})\s+({CH})\s*$", re.IGNORECASE)


def normalize_spacing(ref: str) -> str:
    s = ref.strip()
    s = re.sub(r"\s*:\s*", ":", s)
    s = re.sub(r"\s*,\s*", ",", s)
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s


def strip_abc_suffixes(s: str) -> str:
    return re.sub(r"(\d)[abc]\b", r"\1", s, flags=re.IGNORECASE)


def parse_reference(ref: str) -> Optional[Tuple[str, int, str]]:
    s = normalize_spacing(ref)
    m = REF_REGEX.match(strip_abc_suffixes(s))
    if m:
        book = " ".join(m.group(1).split())
        chapter = int(m.group(2))
        verses = m.group(3)
        return (book, chapter, verses)
    # also allow whole-chapter lines (expand later)
    mch = WHOLE_CH_REGEX.match(ref.strip())
    if mch:
        book = " ".join(mch.group(1).split())
        chapter = int(mch.group(2))
        return (
            book,
            chapter,
            "1-9999",
        )  # sentinel range; we will trim by ESV actual verses
    return None


def expand_verse_list(verses: str) -> List[Tuple[int, int]]:
    """
    Expand a list like "1-3,5,7-8" -> [(1,1),(2,2),(3,3),(5,5),(7,7),(8,8)]
    """
    out: List[Tuple[int, int]] = []
    for seg in verses.split(","):
        seg = seg.strip()
        if not seg:
            continue
        if "-" in seg:
            a, b = seg.split("-", 1)
            try:
                start = int(re.sub(r"[^\d]", "", a))
                end = int(re.sub(r"[^\d]", "", b))
            except Exception:
                continue
            if end < start:
                start, end = end, start
            for v in range(start, end + 1):
                out.append((v, v))
        else:
            v = int(re.sub(r"[^\d]", "", seg))
            out.append((v, v))
    return out


def ensure_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DB_SCHEMA)
    return conn


def verse_exists(
    conn: sqlite3.Connection, book: str, chapter: int, verse: int, translation: str
) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM verses WHERE book=? AND chapter=? AND verse=? AND translation=? LIMIT 1",
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
        "INSERT OR REPLACE INTO verses (book, chapter, verse, translation, text) VALUES (?,?,?,?,?)",
        (book, chapter, verse, translation, text),
    )


def http_get_esv(passage: str, api_key: str) -> Dict:
    """
    Call ESV passage/text with a precise ref (e.g., 'John 3:16'), return parsed JSON.
    """
    qs = {
        "q": passage,
        "include-passage-references": "false",
        "include-verse-numbers": "true",
        "include-footnotes": "false",
        "include-short-copyright": "false",
        "include-headings": "false",
        "include-selahs": "false",
        "indent-poetry": "false",
        "indent-poetry-lines": "false",
    }
    url = f"{ESV_BASE}?{urllib.parse.urlencode(qs)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Token {api_key}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8", errors="replace")
        return json.loads(data)


def extract_single_verse_text(esv_json: Dict) -> str:
    """
    ESV returns a structure with passages as strings; for one-verse requests,
    the passage should contain that single verse with a verse number.
    We'll strip leading verse numbers like '16 ' from the text.
    """
    passages = esv_json.get("passages", [])
    if not passages:
        return ""
    text = passages[0]
    # collapse whitespace/newlines
    text = re.sub(r"\s+", " ", text).strip()
    # remove a leading verse number like "16 " or "1 "
    text = re.sub(r"^\d+\s+", "", text)
    return text


def fetch_and_store_reference(
    conn: sqlite3.Connection, ref: str, api_key: str, translation: str, sleep_s: float
) -> None:
    parsed = parse_reference(ref)
    if not parsed:
        print(f"[WARN] Skipping unparsable reference: {ref}", file=sys.stderr)
        return

    book, chapter, verses = parsed

    # Expand 1-9999 sentinel by probing ESV: we’ll fetch consecutive verses until we hit an empty return.
    if verses == "1-9999":
        start = 1
        # pull until empty; hard stop at 250 to avoid infinite loops
        for v in range(start, 251):
            if verse_exists(conn, book, chapter, v, translation):
                continue
            esv_json = http_get_esv(f"{book} {chapter}:{v}", api_key)
            txt = extract_single_verse_text(esv_json)
            if not txt:
                break
            save_verse(conn, book, chapter, v, translation, txt)
            if sleep_s > 0:
                time.sleep(sleep_s)
        conn.commit()
        return

    # Normal explicit list (e.g., 1-3,5)
    pairs = expand_verse_list(verses)
    for _a, v in pairs:
        if verse_exists(conn, book, chapter, v, translation):
            continue
        esv_json = http_get_esv(f"{book} {chapter}:{v}", api_key)
        txt = extract_single_verse_text(esv_json)
        if not txt:
            print(f"[WARN] Empty text for {book} {chapter}:{v}", file=sys.stderr)
            continue
        save_verse(conn, book, chapter, v, translation, txt)
        if sleep_s > 0:
            time.sleep(sleep_s)
    conn.commit()


def load_references(path: Path) -> List[str]:
    refs: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        refs.append(s)
    return refs


def main():
    parser = argparse.ArgumentParser(
        description="Fetch ESV verses for a list of references and store each verse into SQLite (one verse per row)."
    )
    parser.add_argument("refs_file", help="Text file with one Bible reference per line")
    parser.add_argument(
        "--db",
        default="bible_verse.db",
        help="SQLite database file (default: bible_verse.db)",
    )
    parser.add_argument(
        "--translation", default="ESV", help="Translation code to store (default: ESV)"
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=3.62,
        help="Sleep between verse requests (default: 3.62s)",
    )
    args = parser.parse_args()

    api_key = os.getenv("ESV_API_KEY")
    if not api_key:
        print("[ERROR] ESV_API_KEY is not set.", file=sys.stderr)
        sys.exit(2)

    refs_path = Path(args.refs_file)
    if not refs_path.exists():
        print(f"[ERROR] {refs_path} not found", file=sys.stderr)
        sys.exit(2)

    conn = ensure_db(Path(args.db))
    refs = load_references(refs_path)
    print(f"[INFO] Loaded {len(refs)} references from {refs_path}")

    for i, ref in enumerate(refs, start=1):
        try:
            fetch_and_store_reference(conn, ref, api_key, args.translation, args.sleep)
        except Exception as e:
            print(f"[ERROR] {ref}: {e}", file=sys.stderr)
        if i % 50 == 0:
            print(f"[INFO] Processed {i}/{len(refs)}")

    print("[DONE]")


if __name__ == "__main__":
    main()
