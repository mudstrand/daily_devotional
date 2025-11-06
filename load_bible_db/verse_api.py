#!/usr/bin/env python3
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

DB_PATH = os.getenv("BIBLE_DB", "bible.sqlite")

BOOK = r"(?:[1-3]\s+)?[A-Za-z][A-Za-z ]+"
CH = r"\d+"
VER = r"\d+(?:[abc])?"
RANGE = rf"{VER}(?:-{VER})?"
LIST = rf"{RANGE}(?:,{RANGE})*"
REF_REGEX = re.compile(rf"^\s*({BOOK})\s+({CH}):({LIST})\s*$", re.IGNORECASE)
WHOLE_CH_REGEX = re.compile(rf"^\s*({BOOK})\s+({CH})\s*$", re.IGNORECASE)

app = FastAPI(title="Bible Verse API", version="1.0.0")


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
    mch = WHOLE_CH_REGEX.match(ref.strip())
    if mch:
        book = " ".join(mch.group(1).split())
        chapter = int(mch.group(2))
        return (book, chapter, "1-9999")
    return None


def expand_verse_list(verses: str) -> List[int]:
    """
    Expand "1-3,5,7-8" -> [1,2,3,5,7,8]
    """
    out: List[int] = []
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
            out.extend(list(range(start, end + 1)))
        else:
            v = int(re.sub(r"[^\d]", "", seg))
            out.append(v)
    return out


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class VerseResponse(BaseModel):
    reference: str  # e.g., "John 3:16-18,22"
    translation: str  # "ESV"
    verses: List[Dict[str, Any]]  # [{book,chapter,verse,text},...]


@app.get("/verses", response_model=VerseResponse)
def get_verses(
    q: str = Query(..., description="Reference like 'John 3:16-18,22' or 'Psalm 23'"),
    translation: str = Query("ESV"),
):
    parsed = parse_reference(q)
    if not parsed:
        raise HTTPException(status_code=400, detail="Invalid reference format")

    book, chapter, verses = parsed
    verse_numbers = expand_verse_list(verses)

    conn = get_conn()
    try:
        results: List[Dict[str, Any]] = []
        if verses == "1-9999":
            # pull all verses available for this chapter
            cur = conn.execute(
                "SELECT book, chapter, verse, text FROM verses WHERE book=? AND chapter=? AND translation=? ORDER BY verse ASC",
                (book, chapter, translation),
            )
            rows = cur.fetchall()
            if not rows:
                raise HTTPException(
                    status_code=404, detail="No verses found for chapter"
                )
            for r in rows:
                results.append(
                    {
                        "book": r["book"],
                        "chapter": r["chapter"],
                        "verse": r["verse"],
                        "text": r["text"],
                    }
                )
            # reconstruct final reference using actual last verse
            ref_out = f"{book} {chapter}:1-{rows[-1]['verse']}"
        else:
            # specific list
            for v in verse_numbers:
                cur = conn.execute(
                    "SELECT text FROM verses WHERE book=? AND chapter=? AND verse=? AND translation=?",
                    (book, chapter, v, translation),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Verse not found: {book} {chapter}:{v} ({translation})",
                    )
                results.append(
                    {"book": book, "chapter": chapter, "verse": v, "text": row["text"]}
                )
            ref_out = normalize_spacing(q)

        return VerseResponse(reference=ref_out, translation=translation, verses=results)
    finally:
        conn.close()
