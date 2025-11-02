#!/usr/bin/env python3
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

TARGET_FIELD = "verse"

# ---------------------------
# Patterns: support verse ranges/lists (e.g., 5-6, 7, 9-11) and suffixes (21a, 21b)
# ---------------------------

# Trailing punctuation/boundary class including common Unicode colon lookalikes
TRAIL_PUNCT = r"\s\)\]\}\.,;:\uFE55\u2236\uFF1A\u00B7\u2019\u201D"

# Book + Chapter:Verse(s) — supports ranges/lists and verse letter suffixes (e.g., 21a, 21b)
BOOK_REF_WITH_VERSES = re.compile(
    r"""
    (?:^|[\s\(\[\{,;:])                       # leading boundary
    (                                          # group 1: book name
        (?:[1-3]|I{1,3})?\s*                   # optional numeric/roman prefix
        [A-Za-z][A-Za-z.\s]*?                  # book letters/periods/spaces (lazy)
    )
    \s*
    (\d+)                                      # group 2: chapter
    \s*[:\u2236\uFF1A\uFE55]\s*                # colon or unicode lookalikes
    (\d+[a-cA-C]?)                              # group 3: first verse (digits + optional a/b/c)
    (                                          # group 4: optional more verses (ranges/lists)
        (?:\s*[-–—]\s*\d+[a-cA-C]?             #   - range like -24 or -21a (accept hyphen/en/em dashes)
        | \s*,\s*\d+[a-cA-C]?                  #   , list item like , 27 or , 21b
        )+                                     # one or more additions
    )?                                         # optional
    (?:$|[\s\)\]\}\.,;:\uFE55\u2236\uFF1A\u00B7\u2019\u201D])   # trailing boundary
    """,
    re.VERBOSE,
)

# Book + Chapter only (fallback)
BOOK_REF_CHAPTER_ONLY = re.compile(
    r"""
    (?:^|[\s\(\[\{,;:])                       # leading boundary
    (                                          # group 1: book name
        (?:[1-3]|I{1,3})?\s*
        [A-Za-z][A-Za-z.\s]*?
    )
    \s*
    (\d+)                                      # group 2: chapter
    (?:$|[\s\)\]\}\.,;:\uFE55\u2236\uFF1A\u00B7\u2019\u201D])   # trailing boundary
    """,
    re.VERBOSE,
)

# ---------------------------
# Unicode sanitation
# ---------------------------

# Zero-width / BOMs to remove
ZERO_WIDTHS = "".join(
    [
        "\u200b",  # zero width space
        "\u200c",  # zero width non-joiner
        "\u200d",  # zero width joiner
        "\u2060",  # word joiner
        "\ufeff",  # BOM
    ]
)

# NBSP-like spaces
NBSP_LIKE = "".join(
    [
        "\u00a0",  # no-break space
        "\u202f",  # narrow no-break space
        "\u2007",  # figure space
        "\u2008",  # punctuation space
        "\u2009",  # thin space
        "\u200a",  # hair space
    ]
)

try:
    import regex as regex_mod  # type: ignore

    HAS_REGEX = True
except Exception:
    regex_mod = None
    HAS_REGEX = False

if HAS_REGEX:
    ZW_AND_FORMATS = regex_mod.compile(
        r"[" + re.escape(ZERO_WIDTHS + NBSP_LIKE) + r"]|(\p{Cf})"
    )
else:
    ZW_AND_FORMATS = re.compile(f"[{re.escape(ZERO_WIDTHS + NBSP_LIKE)}]")

PARENS_NORMALIZE = {
    "（": "(",
    "）": ")",
    "﹙": "(",
    "﹚": ")",
    "❨": "(",
    "❩": ")",
}

# ---------------------------
# Helpers
# ---------------------------


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def read_json_file(path: str) -> Optional[Tuple[Any, str]]:
    """
    Read JSON text and strip a leading BOM if present to avoid first-record anomalies.
    Return (parsed_object, original_text_without_bom).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if content.startswith("\ufeff"):
            content = content.lstrip("\ufeff")
        return json.loads(content), content
    except Exception:
        return None


def write_json_file(path: str, data: Any, original_text: str) -> bool:
    """
    Write JSON back to the same path, creating a .bak once per file.
    Supports list or dict (top-level). Preserves UTF-8.
    """
    backup = f"{path}.bak"
    try:
        if not os.path.exists(backup):
            with open(backup, "w", encoding="utf-8") as bf:
                bf.write(original_text)
    except Exception as e:
        print(f"[ERROR] Cannot create backup {backup}: {e}", file=sys.stderr)
        return False

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return True
    except Exception as e:
        print(f"[ERROR] Cannot write {path}: {e}", file=sys.stderr)
        return False


def utc_date_only_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_date_only_from_record(rec: Dict[str, Any]) -> Optional[str]:
    raw = rec.get("dateutc") or rec.get("date_utc")
    if not isinstance(raw, str) or not raw.strip():
        return None
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M %z",
        "%d %b %Y %H:%M:%S %z",
        "%Y-%m-%d",
    ]
    s = raw.strip()
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            continue
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


def sanitize_verse(text: str) -> str:
    """
    Strong unicode sanitation:
    - NFKC normalize
    - remove zero-widths, NBSP-like, and Unicode format chars (Cf) if regex module available
    - collapse any whitespace to a single ASCII space
    - normalize exotic parentheses to ASCII
    - strip
    """
    s = unicodedata.normalize("NFKC", text)
    s = ZW_AND_FORMATS.sub("", s)
    if any(ch in s for ch in PARENS_NORMALIZE):
        s = "".join(PARENS_NORMALIZE.get(ch, ch) for ch in s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _normalize_verses(first: str, tail: Optional[str]) -> str:
    """
    Build a normalized verse string from first + optional tail.
    - Normalize en/em dash to hyphen
    - Remove spaces around '-' and ','
    - Lowercase any letter suffixes (e.g., 21B -> 21b)
    """
    first = re.sub(
        r"^(\d+)([A-Ca-c])$", lambda m: m.group(1) + m.group(2).lower(), first
    )
    if not tail:
        return first
    t = tail.replace("–", "-").replace("—", "-")
    t = re.sub(r"\s*-\s*", "-", t)
    t = re.sub(r"\s*,\s*", ",", t)
    t = re.sub(r"(\d+)([A-Ca-c])", lambda m: m.group(1) + m.group(2).lower(), t)
    return first + t


def _find_last_book_ch_vers(s: str) -> Optional[str]:
    last = None
    for m in BOOK_REF_WITH_VERSES.finditer(s):
        last = m
    if last:
        book = sanitize_verse(last.group(1))
        ch = last.group(2)
        v1 = last.group(3)
        tail = last.group(4) or ""
        verses = _normalize_verses(v1, tail)
        return f"{book} {ch}:{verses}"
    return None


def _find_last_book_ch_only(s: str) -> Optional[str]:
    last = None
    for m in BOOK_REF_CHAPTER_ONLY.finditer(s):
        last = m
    if last:
        book = sanitize_verse(last.group(1))
        ch = last.group(2)
        return f"{book} {ch}"
    return None


def extract_bibleish(text: str) -> Optional[str]:
    """
    Take the last book+chapter:verse(s) anywhere; fallback to last book+chapter.
    """
    if not isinstance(text, str):
        return None
    s = sanitize_verse(text)
    ref = _find_last_book_ch_vers(s)
    if ref:
        return ref
    ref = _find_last_book_ch_only(s)
    if ref:
        return ref
    return None


def is_chapter_reference(ref: str) -> bool:
    """
    True if ref is 'Book Chapter' (no colon).
    """
    return isinstance(ref, str) and ":" not in ref and bool(ref.strip())


def emit_found(
    filename: str, date_only: str, reference: str, print_only_misses: bool
) -> None:
    if not print_only_misses:
        print(f"{filename}, {date_only}: {reference}")


def emit_miss(filename: str, date_only: str, line: int, line_text: str) -> None:
    print(f"{filename}, {date_only}, {line}:DNL")
    print(f"code -g {filename}:{line}")
    print(line_text)


def emit_chapter(
    filename: str, date_only: str, line: int, line_text: str, reference: str
) -> None:
    """
    Emit a chapter-only reference finding with a distinctive tag.
    """
    print(f"{filename}, {date_only}, {line}:DNL-CHAPTER {reference}")
    print(f"code -g {filename}:{line}")
    print(line_text)


# ---------- Robust per-object logging support ----------


def find_top_level_object_spans(content: str) -> List[Tuple[int, int]]:
    """
    For a JSON array file, return [(start_index, end_index_exclusive)] for each top-level object.
    Simple scanner that assumes the top-level is a JSON array of objects.
    """
    spans: List[Tuple[int, int]] = []
    start_arr = content.find("[")
    end_arr = content.rfind("]")
    if start_arr == -1 or end_arr == -1 or end_arr <= start_arr:
        return spans

    i = start_arr + 1
    n = end_arr
    while i < n:
        while i < n and content[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        if content[i] != "{":
            i += 1  # skip until next object
            continue

        depth = 0
        j = i
        in_string = False
        escape = False
        while j <= end_arr:
            ch = content[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        spans.append((i, j + 1))
                        i = j + 1
                        break
            j += 1
        else:
            break

    return spans


def count_lines_up_to(content: str, idx: int) -> int:
    """
    Count lines (1-based) up to idx (exclusive).
    """
    return content.count("\n", 0, idx) + 1


def best_line_for_verse_in_object(
    obj_text: str, verse_value: str, object_start_line: int
) -> Tuple[int, str]:
    """
    Try to find the exact verse line within the object text slice.
    If found, return that line number and text; otherwise return the object's first line.
    """
    lines = obj_text.splitlines()
    rel_line = None
    escaped_val = re.escape(verse_value if isinstance(verse_value, str) else "")
    pat = re.compile(
        r'^\s*"verse"\s*:\s*"' + escaped_val + r'"\s*(?:,|})', re.MULTILINE
    )
    m = pat.search(obj_text)
    if m:
        rel_line = obj_text.count("\n", 0, m.start()) + 1
    else:
        for i, line in enumerate(lines, start=1):
            if '"verse"' in line:
                rel_line = i
                break
    if rel_line is None:
        rel_line = 1
    abs_line = object_start_line + (rel_line - 1)
    line_text = lines[rel_line - 1] if 1 <= rel_line <= len(lines) else ""
    return abs_line, line_text


# ------------------------------------------------------------
# Verse-only normalization (I/II/III -> 1/2/3 in book names)
# ------------------------------------------------------------

ROMAN_TO_ARABIC = {"I": "1", "II": "2", "III": "3"}

# whole-field roman-led reference (after sanitation)
ROMAN_LEAD_FULL = re.compile(
    r"""^
    (?P<num>I{1,3})\s+
    (?P<book>(?:[A-Za-z][A-Za-z.\-']*(?:\s+[A-Za-z][A-Za-z.\-']*)*))\s+
    (?P<chapvers>
        \d+(?::\d+[abc]?(?:\s*[-–—]\s*\d+[abc]?)?)   # 1:2 or 1:2-3
        (?:\s*,\s*(?:\d+(?::\d+[abc]?(?:\s*[-–—]\s*\d+[abc]?)?)|\d+))*  # lists
        |\d+                                         # or Chapter-only
    )
    $""",
    re.VERBOSE,
)

# roman-led reference anywhere in the verse string (supports punctuation boundary)
ROMAN_LEAD_IN_TEXT = re.compile(
    r"""
    (?P<prefix>(?:^|[\s"'(\[{.,;:–—-]))          # start or common boundary/punct
    (?P<num>I{1,3})\s+
    (?P<book>(?:[A-Za-z][A-Za-z.\-']*(?:\s+[A-Za-z][A-Za-z.\-']*)*))\s+
    (?P<chapvers>
        \d+(?::\d+[abc]?(?:\s*[-–—]\s*\d+[abc]?)?)
        (?:\s*,\s*(?:\d+(?::\d+[abc]?(?:\s*[-–—]\s*\d+[abc]?)?)|\d+))*
        |\d+
    )
    """,
    re.VERBOSE,
)


def _norm_roman_to_arabic(roman: str) -> str:
    return ROMAN_TO_ARABIC.get(roman, roman)


def normalize_roman_in_verse_value(
    verse_val: str,
) -> Tuple[str, Optional[Dict[str, str]]]:
    """
    Only update the verse field.
    - If the sanitized verse is a pure roman-led reference, convert I/II/III to 1/2/3.
    - Otherwise, replace roman-led references inside the verse string (prose-safe).
    Returns (updated, change_info or None).
    """
    if not isinstance(verse_val, str) or not verse_val.strip():
        return verse_val, None

    # Try whole-field replacement first (strict, accurate)
    s = sanitize_verse(verse_val)
    m = ROMAN_LEAD_FULL.match(s)
    if m:
        arabic = _norm_roman_to_arabic(m.group("num"))
        updated_core = f"{arabic} {m.group('book')} {m.group('chapvers')}"
        # Preserve original leading/trailing whitespace
        leading_ws = verse_val[: len(verse_val) - len(verse_val.lstrip())]
        trailing_ws = verse_val[len(verse_val.rstrip()) :]
        updated = f"{leading_ws}{updated_core}{trailing_ws}"
        if updated != verse_val:
            return updated, {"from": verse_val, "to": updated}
        return verse_val, None

    # Fallback: in-text replacement within verse (keeps surrounding prose)
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        prefix = m.group("prefix") or ""
        arabic = _norm_roman_to_arabic(m.group("num"))
        out = f"{prefix}{arabic} {m.group('book')} {m.group('chapvers')}"
        if m.group(0) != out:
            changed = True
        return out

    updated = ROMAN_LEAD_IN_TEXT.sub(repl, verse_val)
    if changed and updated != verse_val:
        return updated, {"from": verse_val, "to": updated}
    return verse_val, None


# ------------------------------------------------------------
# NEW: Hyphen-trailing reference normalization (strict)
#   Detect only: "... <text> [-–—] <Book> <ch>:<verses>" at the end,
#   and convert to: "... <text> (<Book> <ch>:<verses>)"
#   Do NOT touch verses that already end with "(Book ch:verses)"
# ------------------------------------------------------------

HYPHEN_REF_AT_END = re.compile(
    r"""
    ^(?P<prefix>.*?)                                  # any verse text, non-greedy
    \s*[-–—]\s*                                       # hyphen/en/em dash separator
    (?P<book>(?:[1-3]|I{1,3})?\s*[A-Za-z][A-Za-z.\s]*?)  # book name (optional numeral)
    \s+
    (?P<ch>\d+)
    \s*[:\u2236\uFF1A\uFE55]\s*
    (?P<vers>\d+[a-cA-C]?(?:\s*(?:[-–—]\s*\d+[a-cA-C]?|\s*,\s*\d+[a-cA-C]?))*)  # ranges/lists
    \s*$                                              # must be the end
    """,
    re.VERBOSE,
)


def normalize_hyphen_ref_at_end(verse_val: str) -> Tuple[str, Optional[Dict[str, str]]]:
    """
    Only handle verses that end with ' - Book Chap:Verses'.
    Ignore lines already ending with a parenthesized reference.
    """
    if not isinstance(verse_val, str) or not verse_val.strip():
        return verse_val, None

    # Fast path: if verse already ends with ')', don't touch it
    if verse_val.rstrip().endswith(")"):
        return verse_val, None

    # NFKC + normalize exotic parentheses just for matching; output uses original text
    s = unicodedata.normalize("NFKC", verse_val)
    s = "".join(PARENS_NORMALIZE.get(ch, ch) for ch in s)

    m = HYPHEN_REF_AT_END.match(s)
    if not m:
        return verse_val, None

    # Rebuild using original prefix exactly
    prefix_len = len(m.group("prefix"))
    prefix_orig = verse_val[:prefix_len]

    book = sanitize_verse(m.group("book"))
    ch = m.group("ch")
    vers = m.group("vers").replace("–", "-").replace("—", "-")
    vers = re.sub(r"\s*-\s*", "-", vers)
    vers = re.sub(r"\s*,\s*", ",", vers)

    # Trim trailing spaces before the hyphen segment to avoid double spaces
    new_core = f"{prefix_orig.rstrip()} ({book} {ch}:{vers})"
    trailing_ws = verse_val[
        len(verse_val.rstrip()) :
    ]  # preserve original trailing whitespace
    updated = new_core + trailing_ws

    if updated != verse_val:
        return updated, {"from": verse_val, "to": updated}
    return verse_val, None


def normalize_record_refs(rec: Dict[str, Any]) -> Optional[Dict[str, Dict[str, str]]]:
    """
    Verse-only normalizer:
    - Convert trailing ' - Book Chap:Verses' to '(Book Chap:Verses)'.
    - Then, IF a hyphen fix happened, normalize roman I/II/III inside that new parenthetical.
    Returns dict of changes (keys: verse-hyphen, verse-roman) or None.
    """
    verse_val = rec.get("verse")
    if not isinstance(verse_val, str):
        return None

    changes: Dict[str, Dict[str, str]] = {}

    # First: apply hyphen-trailing normalization (strict)
    v_after_hyphen, ch1 = normalize_hyphen_ref_at_end(verse_val)
    if ch1:
        rec["verse"] = v_after_hyphen
        changes["verse-hyphen"] = ch1

        # Only then do roman normalization (to avoid touching unrelated verses)
        v_after_roman, ch2 = normalize_roman_in_verse_value(rec.get("verse", ""))
        if ch2:
            rec["verse"] = v_after_roman
            changes["verse-roman"] = ch2

    return changes if changes else None


def normalize_file(
    path: str, name: str, preview: bool
) -> Tuple[int, int, List[Dict[str, str]]]:
    """
    Normalize references for a single JSON file (verse-only).
    Returns (total_records, changed_records, change_entries)
    """
    loaded = read_json_file(path)
    if not loaded:
        return 0, 0, []
    data, original_text = loaded

    total = 0
    changed = 0
    entries: List[Dict[str, str]] = []

    def record_change(idx: int, key: str, ch: Dict[str, str]) -> None:
        entries.append(
            {
                "file": name,
                "index": str(idx),
                "field": key,
                "from": ch["from"],
                "to": ch["to"],
            }
        )

    if isinstance(data, list):
        for i, item in enumerate(data, start=1):
            total += 1
            if isinstance(item, dict):
                ch = normalize_record_refs(item)
                if ch:
                    changed += 1
                    if "verse-hyphen" in ch:
                        record_change(i, "verse", ch["verse-hyphen"])
                    if "verse-roman" in ch:
                        record_change(i, "verse", ch["verse-roman"])
        if not preview and changed > 0:
            write_json_file(path, data, original_text)
    elif isinstance(data, dict):
        total = 1
        ch = normalize_record_refs(data)
        if ch:
            changed = 1
            if "verse-hyphen" in ch:
                record_change(1, "verse", ch["verse-hyphen"])
            if "verse-roman" in ch:
                record_change(1, "verse", ch["verse-roman"])
        if not preview and changed > 0:
            write_json_file(path, data, original_text)
    return total, changed, entries


# ------------------------------------------------------------
# Existing extraction logic (unchanged)
# ------------------------------------------------------------


def process_record(
    rec: Dict[str, Any],
    filename: str,
    file_content: str,
    default_date_only: str,
    print_only_misses: bool,
    is_first_record_in_file: bool,
    object_text: Optional[str] = None,
    object_start_line: Optional[int] = None,
    report_chapters: bool = False,
) -> None:
    date_only = parse_date_only_from_record(rec) or default_date_only
    verse = rec.get(TARGET_FIELD)

    if isinstance(verse, str) and verse.strip():
        ref = extract_bibleish(verse)
        if ref:
            if report_chapters:
                # Only emit if it's a chapter-only reference
                if is_chapter_reference(ref):
                    # Find a good line to point the editor to
                    if object_text is not None and object_start_line is not None:
                        line_no, line_text = best_line_for_verse_in_object(
                            object_text, verse, object_start_line
                        )
                    else:
                        line_no, line_text = 1, ""
                    emit_chapter(filename, date_only, line_no, line_text, ref)
                # When reporting chapters, suppress normal found output
                return
            else:
                emit_found(filename, date_only, ref, print_only_misses)
                return

        # Miss: pick the best line from the object slice if available
        if object_text is not None and object_start_line is not None:
            line_no, line_text = best_line_for_verse_in_object(
                object_text, verse, object_start_line
            )
        else:
            line_no, line_text = 1, ""
        # In chapter-report mode, only chapters are reported; other misses are ignored
        if not report_chapters:
            emit_miss(filename, date_only, line_no, line_text)
        return

    # Missing or non-string verse
    if object_text is not None and object_start_line is not None:
        line_no, line_text = best_line_for_verse_in_object(
            object_text, verse if isinstance(verse, str) else "", object_start_line
        )
    else:
        line_no, line_text = 1, ""
    if not report_chapters:
        emit_miss(filename, date_only, line_no, line_text)


def process_file(
    path: str,
    name: str,
    default_date_only: str,
    print_only_misses: bool,
    report_chapters: bool,
) -> None:
    loaded = read_json_file(path)
    if not loaded:
        if not report_chapters:
            print(f"{name}, {default_date_only}, 1:DNL")
            print("")
        return

    data, content = loaded
    if isinstance(data, list):
        spans = find_top_level_object_spans(content)
        first = True
        for idx, item in enumerate(data):
            if isinstance(item, dict):
                obj_text = None
                obj_start_line = None
                if idx < len(spans):
                    start, end = spans[idx]
                    obj_text = content[start:end]
                    obj_start_line = count_lines_up_to(content, start)
                process_record(
                    item,
                    name,
                    content,
                    default_date_only,
                    print_only_misses,
                    is_first_record_in_file=first,
                    object_text=obj_text,
                    object_start_line=obj_start_line,
                    report_chapters=report_chapters,
                )
            else:
                if not report_chapters:
                    print(f"{name}, {default_date_only}, 1:DNL")
                    print("")
            first = False
    elif isinstance(data, dict):
        process_record(
            data,
            name,
            content,
            default_date_only,
            print_only_misses,
            is_first_record_in_file=True,
            object_text=content,
            object_start_line=1,
            report_chapters=report_chapters,
        )
    else:
        if not report_chapters:
            print(f"{name}, {default_date_only}, 1:DNL")
            print("")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------


def _oneline(s: str) -> str:
    if s is None:
        return ""
    return s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Extract Bible references from the 'verse' field. Supports verse ranges/lists (e.g., 5-6, 7, 9-11) and suffixes (21a/b/c). Robust unicode sanitation. --chapters reports full-chapter references with file and line info. Optional --normalize_refs converts only trailing '- Book ch:verses' to '(Book ch:verses)' and then normalizes roman book numerals if changed."
    )
    ap.add_argument(
        "--dir",
        default=None,
        help="Directory to scan for JSON files (default: script directory). Ignored if filenames are provided.",
    )
    ap.add_argument(
        "--print-only-misses",
        action="store_true",
        help="Print only unparsable lines (DNL) and the source line; suppress successful extractions.",
    )
    ap.add_argument(
        "--chapters",
        action="store_true",
        help="Report only references that are full chapters (Book Chapter), printing filename, date, line, a code -g jump, and the line text.",
    )
    # NEW flags
    ap.add_argument(
        "--normalize_refs",
        action="store_true",
        help="Normalize ONLY verse values: convert trailing '- Book ch:verses' to '(Book ch:verses)'; if changed, also convert book prefixes I/II/III to 1/2/3 inside the verse.",
    )
    ap.add_argument(
        "--preview",
        action="store_true",
        help="With --normalize_refs, preview changes (cur/upd) but do not modify files.",
    )
    ap.add_argument(
        "filenames",
        nargs="*",
        help="One or more JSON file paths to process. If provided, directory scanning is skipped.",
    )
    args = ap.parse_args()

    default_date_only = utc_date_only_now()
    print_only_misses = args.print_only_misses
    report_chapters = args.chapters

    # First, run the existing extraction/reporting pass (unchanged behavior)
    if args.filenames:
        exit_code = 0
        for path in args.filenames:
            name = os.path.basename(path)
            if not os.path.isfile(path):
                print(f"Error: not a file or not found: {path}", file=sys.stderr)
                exit_code = 1
                continue
            process_file(
                path, name, default_date_only, print_only_misses, report_chapters
            )
        if not args.normalize_refs:
            sys.exit(exit_code)
    else:
        base = args.dir or script_dir()
        try:
            entries = sorted(os.listdir(base))
        except Exception as e:
            print(f"Error reading directory {base}: {e}", file=sys.stderr)
            sys.exit(1)

        files_seen = 0
        for name in entries:
            if not name.endswith(".json"):
                continue
            files_seen += 1
            process_file(
                os.path.join(base, name),
                name,
                default_date_only,
                print_only_misses,
                report_chapters,
            )
        if files_seen == 0:
            print("No JSON files found", file=sys.stderr)
            if not args.normalize_refs:
                sys.exit(1)

    # If normalization requested, run a separate pass over the same targets
    if args.normalize_refs:
        if args.filenames:
            targets = args.filenames
        else:
            base = args.dir or script_dir()
            try:
                targets = [
                    os.path.join(base, n)
                    for n in sorted(os.listdir(base))
                    if n.endswith(".json")
                ]
            except Exception as e:
                print(f"Error reading directory {base}: {e}", file=sys.stderr)
                sys.exit(1)

        grand_total = 0
        grand_changed = 0
        all_entries: List[Dict[str, str]] = []

        for path in targets:
            name = os.path.basename(path)
            t, c, ents = normalize_file(path, name, preview=args.preview)
            grand_total += t
            grand_changed += c
            all_entries.extend(ents)

        if args.preview:
            print(
                f"Preview mode: {grand_changed} of {grand_total} records would change.\n"
            )
            for e in all_entries:
                print(f"- {e['file']} record #{e['index']} ({e['field']}):")
                print(f'cur: "{_oneline(e["from"])}"')
                print(f'upd: "{_oneline(e["to"])}"')
        else:
            print(
                f"Normalization complete. Updated {grand_changed} of {grand_total} records."
            )
            print("Backups created as .bak for files that changed.")


if __name__ == "__main__":
    main()
