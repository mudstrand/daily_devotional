#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

# =========================
# Data structures
# =========================


@dataclass(frozen=True)
class VerseRef:
    book: str
    chapter: int
    verses: Optional[str]  # None for whole chapter


@dataclass(frozen=True)
class NormalizedRef:
    book: str
    chapter: int
    parts: Tuple[Tuple[int, Optional[int]], ...]  # (start, end_or_None)
    original_verses: Optional[str]


# =========================
# Canon and aliases
# =========================

CANONICAL_BOOKS = [
    "Genesis",
    "Exodus",
    "Leviticus",
    "Numbers",
    "Deuteronomy",
    "Joshua",
    "Judges",
    "Ruth",
    "1 Samuel",
    "2 Samuel",
    "1 Kings",
    "2 Kings",
    "1 Chronicles",
    "2 Chronicles",
    "Ezra",
    "Nehemiah",
    "Esther",
    "Job",
    "Psalm",
    "Proverbs",
    "Ecclesiastes",
    "Song of Songs",
    "Isaiah",
    "Jeremiah",
    "Lamentations",
    "Ezekiel",
    "Daniel",
    "Hosea",
    "Joel",
    "Amos",
    "Obadiah",
    "Jonah",
    "Micah",
    "Nahum",
    "Habakkuk",
    "Zephaniah",
    "Haggai",
    "Zechariah",
    "Malachi",
    "Matthew",
    "Mark",
    "Luke",
    "John",
    "Acts",
    "Romans",
    "1 Corinthians",
    "2 Corinthians",
    "Galatians",
    "Ephesians",
    "Philippians",
    "Colossians",
    "1 Thessalonians",
    "2 Thessalonians",
    "1 Timothy",
    "2 Timothy",
    "Titus",
    "Philemon",
    "Hebrews",
    "James",
    "1 Peter",
    "2 Peter",
    "1 John",
    "2 John",
    "3 John",
    "Jude",
    "Revelation",
]

ALIASES: Dict[str, str] = {
    "ps": "Psalm",
    "psa": "Psalm",
    "psalm": "Psalm",
    "psalms": "Psalm",
    "prov": "Proverbs",
    "pro": "Proverbs",
    "pr": "Proverbs",
    "ecc": "Ecclesiastes",
    "eccl": "Ecclesiastes",
    "qoheleth": "Ecclesiastes",
    "song": "Song of Songs",
    "song of solomon": "Song of Songs",
    "canticles": "Song of Songs",
    "sos": "Song of Songs",
    "isa": "Isaiah",
    "isaiah": "Isaiah",
    "jer": "Jeremiah",
    "lam": "Lamentations",
    "ezek": "Ezekiel",
    "eze": "Ezekiel",
    "dan": "Daniel",
    "hos": "Hosea",
    "zec": "Zechariah",
    "zechariah": "Zechariah",
    "mal": "Malachi",
    "mal.": "Malachi",
    "mt": "Matthew",
    "matt": "Matthew",
    "matt.": "Matthew",
    "mk": "Mark",
    "mrk": "Mark",
    "mark.": "Mark",
    "lk": "Luke",
    "luk": "Luke",
    "luke.": "Luke",
    "jn": "John",
    "jhn": "John",
    "john.": "John",
    "jno": "John",
    "jno.": "John",
    "acts": "Acts",
    "rom": "Romans",
    "rom.": "Romans",
    "col": "Colossians",
    "col.": "Colossians",
    "gal": "Galatians",
    "gal.": "Galatians",
    "eph": "Ephesians",
    "eph.": "Ephesians",
    "phil": "Philippians",
    "phil.": "Philippians",
    "phl": "Philippians",
    "phl.": "Philippians",
    "php": "Philippians",
    "tit": "Titus",
    "philem": "Philemon",
    "heb": "Hebrews",
    "jas": "James",
    "jam": "James",
    "jam.": "James",
    "rev": "Revelation",
    "revelations": "Revelation",
    "rev.": "Revelation",
    "jude": "Jude",
    # Thessalonians
    "thess": "1 Thessalonians",
    "thessalonians": "1 Thessalonians",
    "i thess": "1 Thessalonians",
    "i thess.": "1 Thessalonians",
    "1 thess": "1 Thessalonians",
    "1 thess.": "1 Thessalonians",
    "ii thess": "2 Thessalonians",
    "ii thess.": "2 Thessalonians",
    "2 thess": "2 Thessalonians",
    "2 thess.": "2 Thessalonians",
    # Timothy
    "i tim": "1 Timothy",
    "i tim.": "1 Timothy",
    "1 tim": "1 Timothy",
    "1 tim.": "1 Timothy",
    "1 ti": "1 Timothy",
    "1 ti.": "1 Timothy",
    "ii tim": "2 Timothy",
    "ii tim.": "2 Timothy",
    "2 tim": "2 Timothy",
    "2 tim.": "2 Timothy",
    "2 tm": "2 Timothy",
    "2 tm.": "2 Timothy",
    # Peter
    "i pet": "1 Peter",
    "i pet.": "1 Peter",
    "1 pet": "1 Peter",
    "1 pet.": "1 Peter",
    "1 pt": "1 Peter",
    "1 pt.": "1 Peter",
    "ii pet": "2 Peter",
    "ii pet.": "2 Peter",
    "2 pet": "2 Peter",
    "2 pet.": "2 Peter",
    "2 pt": "2 Peter",
    "2 pt.": "2 Peter",
    # John (epistles)
    "i jn": "1 John",
    "i jn.": "1 John",
    "1 jn": "1 John",
    "1 jn.": "1 John",
    "1 john": "1 John",
    "1 john.": "1 John",
    "ii jn": "2 John",
    "ii jn.": "2 John",
    "2 jn": "2 John",
    "2 jn.": "2 John",
    "2 john": "2 John",
    "2 john.": "2 John",
    "iii jn": "3 John",
    "iii jn.": "3 John",
    "3 jn": "3 John",
    "3 jn.": "3 John",
    "3 john": "3 John",
    "3 john.": "3 John",
    # Corinthians
    "i cor": "1 Corinthians",
    "i cor.": "1 Corinthians",
    "1 cor": "1 Corinthians",
    "1 cor.": "1 Corinthians",
    "1 co": "1 Corinthians",
    "1 co.": "1 Corinthians",
    "ii cor": "2 Corinthians",
    "ii cor.": "2 Corinthians",
    "2 cor": "2 Corinthians",
    "2 cor.": "2 Corinthians",
    "2 co": "2 Corinthians",
    "2 co.": "2 Corinthians",
    # Samuel/Kings/Chronicles
    "i sam": "1 Samuel",
    "i sam.": "1 Samuel",
    "1 sam": "1 Samuel",
    "1 sam.": "1 Samuel",
    "ii sam": "2 Samuel",
    "ii sam.": "2 Samuel",
    "2 sam": "2 Samuel",
    "2 sam.": "2 Samuel",
    "i kings": "1 Kings",
    "i kings.": "1 Kings",
    "i king": "1 Kings",
    "i king.": "1 Kings",
    "1 kings": "1 Kings",
    "1 kings.": "1 Kings",
    "ii kings": "2 Kings",
    "ii kings.": "2 Kings",
    "2 kings": "2 Kings",
    "2 kings.": "2 Kings",
    "i chr": "1 Chronicles",
    "i chr.": "1 Chronicles",
    "i chron": "1 Chronicles",
    "i chron.": "1 Chronicles",
    "1 chr": "1 Chronicles",
    "1 chr.": "1 Chronicles",
    "ii chr": "2 Chronicles",
    "ii chr.": "2 Chronicles",
    "2 chr": "2 Chronicles",
    "2 chr.": "2 Chronicles",
    # Joshua
    "jos": "Joshua",
    "jos.": "Joshua",
    "josh": "Joshua",
    "josh.": "Joshua",
    # Policy default: "Corinthians" alone -> 1 Corinthians (change if you prefer 2 Corinthians)
    "corinthians": "1 Corinthians",
}

ROMAN_TO_ARABIC = {"i": "1", "ii": "2", "iii": "3"}

# =========================
# Normalization helpers
# =========================


def normalize_text_for_refs(s: str) -> str:
    if not s:
        return s
    s = s.replace("\u00a0", " ")
    # Normalize bullet-like chars to dash and collapse whitespace
    s = re.sub(r"[•·▪▶❖►]", "-", s)
    s = re.sub(r"\s+", " ", s)

    # Normalize Unicode dashes / minus / tilde to hyphen
    s = s.replace("—", "-").replace("–", "-").replace("~", "-").replace("−", "-")

    # If whole text starts with a dash-like prefix, strip it
    s = re.sub(r"^\s*[-–—]\s*", "", s)

    # Insert missing space between letters and first digit (Psalm119 -> Psalm 119)
    s = re.sub(r"([A-Za-z\.])(\d)", r"\1 \2", s)

    # Semicolon as chapter:verse separator (15; 15 -> 15:15)
    s = re.sub(r"(\d)\s*;\s*(\d)", r"\1:\2", s)

    # Double colon chapter:verse:verse -> chapter:verse-verse
    s = re.sub(r"(\b\d{1,3}):(\d{1,3}):(\d{1,3}\b)", r"\1:\2-\3", s)

    # Trim spaces around punctuation in verse segments
    s = re.sub(r"\s*:\s*", ":", s)
    s = re.sub(r"\s*,\s*", ",", s)
    s = re.sub(r"\s*-\s*", "-", s)

    return s.strip()


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def romanize_numbered_book_prefix(book_raw: str) -> str:
    s = book_raw.strip()
    m = re.match(r"^(?P<roman>i{1,3})\.?\s+(?P<rest>.+)$", s, re.IGNORECASE)
    if m:
        roman = m.group("roman").lower()
        rest = m.group("rest")
        arabic = ROMAN_TO_ARABIC.get(roman)
        if arabic:
            return f"{arabic} {rest}"
    return s


def canonicalize_book(raw: str) -> Optional[str]:
    s = _normalize_spaces(raw)
    s = romanize_numbered_book_prefix(s)
    lower = s.lower().rstrip(".,")
    for b in CANONICAL_BOOKS:
        if b.lower() == lower:
            return b

    lower_norm = _normalize_spaces(lower)
    if lower_norm in ALIASES:
        return ALIASES[lower_norm]

    m = re.match(r"^(?:(1|2|3)\s*)([a-z][a-z\s\.]+)$", lower_norm)
    if m:
        num, name = m.groups()
        name = _normalize_spaces(name.replace(".", ""))
        candidate = f"{num} {name}".title()
        for b in CANONICAL_BOOKS:
            if b.lower() == candidate.lower():
                return b

    candidate = s.replace(".", "").title()
    for b in CANONICAL_BOOKS:
        if b.lower() == candidate.lower():
            return b

    return None


# =========================
# Parsing
# =========================

PARENS_REF_RE = re.compile(r"\(([^()]*\d[^()]*)\)")

MAIN_REF_RE = re.compile(
    r"""
    ^\s*
    (?P<book>(?:[1-3]|I{1,3})\.?\s+[A-Za-z][A-Za-z\.\s]+?|[A-Za-z][A-Za-z\.\s]+?)
    \s+
    (?P<chapter>\d{1,3})
    (?:\s*:\s*(?P<verses>[\dA-Za-z,\-\s]+))?
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# More permissive: start of string, whitespace, quotes, or dash; then Book Chapter[:Verses]
BARE_REF_FINDER = re.compile(
    r"""
    (?:(?<=\s)|^|[("'“”‘’\-–—])
    (?P<book>(?:[1-3]|I{1,3})\.?\s+[A-Za-z][A-Za-z\.\s]+|[A-Za-z][A-Za-z\.\s]+)
    \s+
    (?P<chapter>\d{1,3})
    (?:\s*:\s*(?P<verses>[\dA-Za-z,\-\s]+))?
    \s*\)?
    (?=$|[\s\.,;:!?"\)])
    """,
    re.VERBOSE | re.IGNORECASE,
)


def parse_verses_segment(
    verses: Optional[str],
) -> Tuple[Tuple[int, Optional[int]], ...]:
    if not verses:
        return tuple()
    parts: List[Tuple[int, Optional[int]]] = []
    tokens = [t.strip() for t in verses.split(",") if t.strip()]
    for token in tokens:
        if "-" in token:
            a, b = token.split("-", 1)
            ma = re.match(r"\d+", a.strip())
            mb = re.match(r"\d+", b.strip())
            if not ma or not mb:
                continue
            a_num = int(ma.group(0))
            b_num = int(mb.group(0))
            if b_num < a_num:
                a_num, b_num = b_num, a_num
            parts.append((a_num, b_num))
        else:
            m = re.match(r"(\d+)", token)
            if m:
                v = int(m.group(1))
                parts.append((v, None))
    return tuple(parts)


def parse_reference_string(candidate: str) -> Optional[VerseRef]:
    m = MAIN_REF_RE.match(candidate)
    if not m:
        return None
    book_raw = m.group("book") or ""
    chapter_str = m.group("chapter")
    verses_raw = m.group("verses")

    book = canonicalize_book(book_raw)
    if not book:
        return None

    chapter = int(chapter_str)
    verses_norm = None
    if verses_raw:
        vv = verses_raw.strip().replace(" ", "")
        verses_norm = vv
    return VerseRef(book=book, chapter=chapter, verses=verses_norm)


def to_normalized(ref: VerseRef) -> NormalizedRef:
    parts = parse_verses_segment(ref.verses)
    return NormalizedRef(
        book=ref.book, chapter=ref.chapter, parts=parts, original_verses=ref.verses
    )


def extract_references_from_text(text: str) -> List[VerseRef]:
    norm_text = normalize_text_for_refs(text or "")
    found: List[VerseRef] = []
    seen = set()

    # From parentheses
    for m in PARENS_REF_RE.finditer(norm_text):
        cand = m.group(1).strip()
        ref = parse_reference_string(cand)
        if ref:
            key = (ref.book, ref.chapter, ref.verses or "")
            if key not in seen:
                seen.add(key)
                found.append(ref)

    # Bare references across the whole string
    for m in BARE_REF_FINDER.finditer(norm_text):
        book = m.group("book")
        chapter = m.group("chapter")
        verses = m.group("verses")
        cand = f"{book} {chapter}" + (f":{verses}" if verses else "")
        ref = parse_reference_string(cand)
        if ref:
            key = (ref.book, ref.chapter, ref.verses or "")
            if key not in seen:
                seen.add(key)
                found.append(ref)

    # Per-line fallback (helps with refs on their own line after a block of text)
    for line in norm_text.splitlines():
        line = line.strip()
        if not line:
            continue
        for m in BARE_REF_FINDER.finditer(line):
            book = m.group("book")
            chapter = m.group("chapter")
            verses = m.group("verses")
            cand = f"{book} {chapter}" + (f":{verses}" if verses else "")
            ref = parse_reference_string(cand)
            if ref:
                key = (ref.book, ref.chapter, ref.verses or "")
                if key not in seen:
                    seen.add(key)
                    found.append(ref)

    return found


# =========================
# Hooks for steps 2–4 (stubs)
# =========================


class NIVProvider:
    version = "NIV"

    def get_text(self, nref: NormalizedRef) -> str:
        return f"[NIV TEXT for {nref.book} {nref.chapter}" + (
            f":{nref.original_verses}]" if nref.original_verses else "]"
        )


class CacheBackend:
    def get(self, key: str) -> Optional[str]:
        return None

    def set(self, key: str, text: str) -> None:
        pass


def make_cache_key(nref: NormalizedRef, version: str = "NIV") -> str:
    return f"{version}|{nref.book}|{nref.chapter}|{nref.original_verses or ''}"


def get_text_with_cache(
    nref: NormalizedRef, provider: NIVProvider, cache: CacheBackend
) -> str:
    key = make_cache_key(nref, provider.version)
    cached = cache.get(key)
    if cached is not None:
        return cached
    text = provider.get_text(nref)
    cache.set(key, text)
    return text


def update_original_json_record(
    record: Dict[str, Any], ref_to_text: Dict[str, str]
) -> Dict[str, Any]:
    verse_field = record.get("verse", "") or ""
    refs = extract_references_from_text(verse_field)
    normalized_refs = [to_normalized(r) for r in refs]
    items = []
    for nref in normalized_refs:
        key = make_cache_key(nref)
        items.append(
            {
                "reference": f"{nref.book} {nref.chapter}"
                + (f":{nref.original_verses}" if nref.original_verses else ""),
                "version": "NIV",
                "text": ref_to_text.get(key, ""),
            }
        )
    out = dict(record)
    out["verse_text_niv"] = items
    return out


# =========================
# I/O with metadata (NDJSON line numbers)
# =========================


def read_json_any_with_meta(path: str):
    """
    Returns (records, meta_list)
    meta_list[i] has: {"record_type": "array|object|ndjson", "line": int|None}
    """
    with open(path, "r", encoding="utf-8") as f:
        data = f.read().strip()
    if not data:
        return [], []
    # Try array or object
    try:
        obj = json.loads(data)
        if isinstance(obj, list):
            return obj, [{"record_type": "array", "line": None} for _ in obj]
        elif isinstance(obj, dict):
            return [obj], [{"record_type": "object", "line": None}]
    except json.JSONDecodeError:
        pass
    # NDJSON
    records, meta = [], []
    for lineno, line in enumerate(data.splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
            if isinstance(rec, dict):
                records.append(rec)
                meta.append({"record_type": "ndjson", "line": lineno})
        except json.JSONDecodeError:
            sys.stderr.write(
                f"Skipping invalid JSON line {lineno} in {path}: {line[:120]}...\n"
            )
    return records, meta


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================
# CLI actions
# =========================


def action_parse_only(args: argparse.Namespace) -> None:
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    for in_path in args.input:
        records, meta = read_json_any_with_meta(in_path)
        parsed_output = []
        for idx, rec in enumerate(records):
            verse_text = rec.get("verse", "") or ""
            refs = extract_references_from_text(verse_text)
            norm = [to_normalized(r) for r in refs]
            parsed_output.append(
                {
                    "file": in_path,
                    "index": idx,
                    "record_type": meta[idx]["record_type"],
                    "record_line": meta[idx]["line"],
                    "message_id": rec.get("message_id"),
                    "references": [
                        {
                            "book": n.book,
                            "chapter": n.chapter,
                            "verses": n.original_verses,  # None => whole chapter
                            "parts": [
                                {"start": a, "end": (b if b is not None else a)}
                                for (a, b) in n.parts
                            ],
                        }
                        for n in norm
                    ],
                    "raw": verse_text,
                }
            )
        base = os.path.basename(in_path)
        stem = os.path.splitext(base)[0]
        out_path = os.path.join(out_dir, f"{stem}.parsed.json")
        write_json(out_path, parsed_output)
        print(f"Wrote {out_path} with {len(parsed_output)} records")


def action_verify(args: argparse.Namespace) -> None:
    total_records = 0
    verse_fields_present = 0
    success_records = 0
    failure_records = 0
    findings: List[Dict[str, Any]] = []

    for in_path in args.input:
        records, meta = read_json_any_with_meta(in_path)
        total_records += len(records)
        for idx, rec in enumerate(records):
            info = meta[idx]
            verse_text = rec.get("verse")
            if verse_text is not None and str(verse_text).strip() != "":
                verse_fields_present += 1
            refs = extract_references_from_text(verse_text or "")
            ok = len(refs) > 0
            if ok:
                success_records += 1
            else:
                failure_records += 1
            if args.keep_details or not ok:
                findings.append(
                    {
                        "file": in_path,
                        "index": idx,
                        "record_type": info["record_type"],
                        "record_line": info["line"],
                        "message_id": rec.get("message_id"),
                        "has_verse_field": verse_text is not None,
                        "verse_field_text": (verse_text or "")[:400],
                        "parsed_count": len(refs),
                        "parsed_refs": [
                            {"book": r.book, "chapter": r.chapter, "verses": r.verses}
                            for r in refs
                        ],
                    }
                )

    print("Verification summary")
    print(f"- files: {len(args.input)}")
    print(f"- total records: {total_records}")
    print(f"- records with non-empty 'verse' field: {verse_fields_present}")
    print(f"- successfully parsed >=1 reference: {success_records}")
    print(f"- failed to parse any reference: {failure_records}")
    success_rate = (
        (success_records / verse_fields_present * 100.0)
        if verse_fields_present
        else 0.0
    )
    print(f"- success rate (of records with verse text): {success_rate:.2f}%")

    if args.report_json:
        os.makedirs(os.path.dirname(args.report_json), exist_ok=True)
        write_json(
            args.report_json,
            {
                "summary": {
                    "files": len(args.input),
                    "total_records": total_records,
                    "verse_fields_present": verse_fields_present,
                    "success_records": success_records,
                    "failure_records": failure_records,
                    "success_rate": success_rate,
                },
                "findings": findings
                if args.keep_details
                else [f for f in findings if f["parsed_count"] == 0],
            },
        )
        print(f"Wrote JSON report to {args.report_json}")

    if args.report_csv:
        os.makedirs(os.path.dirname(args.report_csv), exist_ok=True)
        with open(args.report_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "file",
                    "index",
                    "record_type",
                    "record_line",
                    "message_id",
                    "has_verse_field",
                    "parsed_count",
                    "book",
                    "chapter",
                    "verses",
                    "verse_field_text",
                ]
            )
            for fnd in findings:
                if not args.keep_details and fnd["parsed_count"] > 0:
                    continue
                if fnd["parsed_count"] == 0:
                    w.writerow(
                        [
                            fnd["file"],
                            fnd["index"],
                            fnd["record_type"],
                            fnd["record_line"],
                            fnd["message_id"],
                            fnd["has_verse_field"],
                            0,
                            "",
                            "",
                            "",
                            fnd["verse_field_text"],
                        ]
                    )
                else:
                    for r in fnd["parsed_refs"]:
                        w.writerow(
                            [
                                fnd["file"],
                                fnd["index"],
                                fnd["record_type"],
                                fnd["record_line"],
                                fnd["message_id"],
                                fnd["has_verse_field"],
                                fnd["parsed_count"],
                                r["book"],
                                r["chapter"],
                                r["verses"],
                                fnd["verse_field_text"],
                            ]
                        )
        print(f"Wrote CSV report to {args.report_csv}")

    if failure_records > 0 and not args.allow_fail:
        sys.exit(1)


def action_fetch_mock_map(args: argparse.Namespace) -> None:
    out_path = args.out
    provider = NIVProvider()
    entries: Dict[str, Dict[str, str]] = {}
    # Collate unique references across files
    for in_path in args.input:
        records, _ = read_json_any_with_meta(in_path)
        for rec in records:
            refs = extract_references_from_text(rec.get("verse", "") or "")
            for r in refs:
                nref = to_normalized(r)
                key = make_cache_key(nref, provider.version)
                if key not in entries:
                    entries[key] = {
                        "reference": f"{nref.book} {nref.chapter}"
                        + (f":{nref.original_verses}" if nref.original_verses else ""),
                        "version": provider.version,
                        "text": provider.get_text(nref),  # mock
                    }
    write_json(out_path, {"entries": entries})
    print(f"Wrote mock text map to {out_path} with {len(entries)} entries")


def action_update_mock(args: argparse.Namespace) -> None:
    in_path = args.input
    out_path = args.out
    records, _meta = read_json_any_with_meta(in_path)

    provider = NIVProvider()

    # simple in-memory cache
    class InMemoryCache(CacheBackend):
        def __init__(self):
            self.map: Dict[str, str] = {}

        def get(self, key: str) -> Optional[str]:
            return self.map.get(key)

        def set(self, key: str, text: str) -> None:
            self.map[key] = text

    cache = InMemoryCache()

    updated = []
    for rec in records:
        verse_text = rec.get("verse", "") or ""
        refs = extract_references_from_text(verse_text)
        normalized_refs = [to_normalized(r) for r in refs]

        # fetch or mock-fetch with cache
        ref_to_text: Dict[str, str] = {}
        for nref in normalized_refs:
            key = make_cache_key(nref, provider.version)
            text = get_text_with_cache(nref, provider, cache)
            ref_to_text[key] = text

        # attach mock NIV text
        updated.append(update_original_json_record(rec, ref_to_text))

    write_json(out_path, updated)
    print(f"Wrote updated records with mock NIV text to {out_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract, verify, and mock-fetch Bible references from JSON records."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("parse", help="Parse references only, write *.parsed.json")
    sp.add_argument(
        "--out-dir", default="./out", help="Directory to write parsed files"
    )
    sp.add_argument("input", nargs="+", help="Input JSON files")
    sp.set_defaults(func=action_parse_only)

    sv = sub.add_parser(
        "verify",
        help="Test-mode: run over many files, summarize success/fail, write reports",
    )
    sv.add_argument(
        "input", nargs="+", help="Input JSON files (array, object, or NDJSON)"
    )
    sv.add_argument("--report-json", help="Path to write a JSON report")
    sv.add_argument("--report-csv", help="Path to write a CSV report")
    sv.add_argument(
        "--keep-details",
        action="store_true",
        help="Include details for successful parses in reports",
    )
    sv.add_argument(
        "--allow-fail",
        action="store_true",
        help="Do not exit non-zero if failures are found",
    )
    sv.set_defaults(func=action_verify)

    sf = sub.add_parser(
        "fetch-mock-map",
        help="Create a mock verse text map (unique refs) from input files",
    )
    sf.add_argument("input", nargs="+", help="Input JSON files")
    sf.add_argument("--out", required=True, help="Output JSON (map) file path")
    sf.set_defaults(func=action_fetch_mock_map)

    su = sub.add_parser(
        "update-mock", help="Attach mock NIV text to records and write updated JSON"
    )
    su.add_argument("input", help="Input JSON file (array, object, or NDJSON)")
    su.add_argument("--out", required=True, help="Output JSON file path")
    su.set_defaults(func=action_update_mock)

    return p


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
