#!/usr/bin/env python3
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

TARGET_FIELD = "verse"

# Trailing punctuation/boundary class including common Unicode colon lookalikes
TRAIL_PUNCT = r"\s\)\]\}\.,;:!?\uFE55\u2236\uFF1A\u00B7\u2019\u201D"

BOOK_REF_WITH_COLON = re.compile(
    rf"""
    (?:^|[\s\(\[\{{,;:])                 # leading boundary
    (                                     # group 1: book name
        (?:[1-3]|I{{1,3}})?\s*            # optional numeric/roman prefix
        [A-Za-z][A-Za-z.\s]*?             # book letters/periods/spaces (lazy)
    )
    \s*
    (\d+)                                  # group 2: chapter
    \s*[:\u2236\uFF1A\uFE55]\s*            # colon or unicode lookalikes
    (\d+)                                  # group 3: verse
    (?:$|[{TRAIL_PUNCT}])                  # trailing boundary
    """,
    re.VERBOSE,
)

BOOK_REF_ANY_DIGIT = re.compile(
    rf"""
    (?:^|[\s\(\[\{{,;:])                  # leading boundary
    (                                     # group 1: book name
        (?:[1-3]|I{{1,3}})?\s*
        [A-Za-z][A-Za-z.\s]*?
    )
    \s*
    (\d+)                                  # group 2: number (chapter)
    (?:$|[{TRAIL_PUNCT}])                  # trailing boundary
    """,
    re.VERBOSE,
)

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
ZERO_WIDTHS_RE = re.compile(f"[{re.escape(ZERO_WIDTHS)}]")

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


def _find_last_book_ch_vers(s: str) -> Optional[str]:
    last = None
    for m in BOOK_REF_WITH_COLON.finditer(s):
        last = m
    if last:
        book = sanitize_verse(last.group(1))
        ch = last.group(2)
        vs = last.group(3)
        return f"{book} {ch}:{vs}"
    return None


def _find_last_book_ch_only(s: str) -> Optional[str]:
    last = None
    for m in BOOK_REF_ANY_DIGIT.finditer(s):
        last = m
    if last:
        book = sanitize_verse(last.group(1))
        ch = last.group(2)
        return f"{book} {ch}"
    return None


def extract_bibleish(text: str) -> Optional[str]:
    """
    Take the last book+chapter:verse anywhere; fallback to last book+chapter.
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


def emit_found(
    filename: str, date_only: str, reference: str, print_only_misses: bool
) -> None:
    if not print_only_misses:
        print(f"{filename}, {date_only}: {reference}")


def emit_miss(filename: str, date_only: str, line: int, line_text: str) -> None:
    print(f"{filename}, {date_only}, {line}:DNL")
    print(f"code -g {filename}:{line}")
    print(line_text)


# ---------- New: robust per-object logging support ----------


def find_top_level_object_spans(content: str) -> List[Tuple[int, int]]:
    """
    For a JSON array file, return [(start_index, end_index_exclusive)] for each top-level object.
    Simple scanner that assumes the top-level is a JSON array of objects.
    """
    spans: List[Tuple[int, int]] = []

    # Find the first '[' and last ']' to bound the array
    start_arr = content.find("[")
    end_arr = content.rfind("]")
    if start_arr == -1 or end_arr == -1 or end_arr <= start_arr:
        return spans

    i = start_arr + 1
    n = end_arr
    while i < n:
        # Skip whitespace and commas
        while i < n and content[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        if content[i] != "{":
            # Not an object start; try to skip (defensive)
            i += 1
            continue

        # We are at the start of an object; find its matching closing brace at depth 0
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
                        # end of object is at j
                        spans.append((i, j + 1))
                        i = j + 1
                        break
            j += 1
        else:
            # Unterminated; abort
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
    # Search for the "verse": "..." within the slice only
    # Use a tolerant regex to avoid escape/spacing mismatches in JSON
    escaped_val = re.escape(verse_value if isinstance(verse_value, str) else "")
    pat = re.compile(
        r'^\s*"verse"\s*:\s*"' + escaped_val + r'"\s*(?:,|})', re.MULTILINE
    )
    m = pat.search(obj_text)
    if m:
        rel_line = obj_text.count("\n", 0, m.start()) + 1
    else:
        # fallback: any line containing the verse key
        for i, line in enumerate(lines, start=1):
            if '"verse"' in line:
                rel_line = i
                break
    if rel_line is None:
        rel_line = 1
    abs_line = object_start_line + (rel_line - 1)
    # Get the exact text of that line (absolute from full file isn't available here, but we return the slice line)
    line_text = lines[rel_line - 1] if 1 <= rel_line <= len(lines) else ""
    return abs_line, line_text


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
) -> None:
    date_only = parse_date_only_from_record(rec) or default_date_only
    verse = rec.get(TARGET_FIELD)

    if isinstance(verse, str) and verse.strip():
        ref = extract_bibleish(verse)
        if ref:
            emit_found(filename, date_only, ref, print_only_misses)
            return

        # Miss: pick the best line from the object slice if available
        if object_text is not None and object_start_line is not None:
            line_no, line_text = best_line_for_verse_in_object(
                object_text, verse, object_start_line
            )
        else:
            # Fallback legacy behavior (can misattribute on duplicates)
            line_no, line_text = 1, ""
        emit_miss(filename, date_only, line_no, line_text)
        return

    # Missing or non-string verse
    if object_text is not None and object_start_line is not None:
        line_no, line_text = best_line_for_verse_in_object(
            object_text, verse if isinstance(verse, str) else "", object_start_line
        )
    else:
        line_no, line_text = 1, ""
    emit_miss(filename, date_only, line_no, line_text)


def process_file(
    path: str, name: str, default_date_only: str, print_only_misses: bool
) -> None:
    loaded = read_json_file(path)
    if not loaded:
        print(f"{name}, {default_date_only}, 1:DNL")
        print("")
        return

    data, content = loaded
    if isinstance(data, list):
        # Build object spans once for precise logging
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
                )
            else:
                print(f"{name}, {default_date_only}, 1:DNL")
                print("")
            first = False
    elif isinstance(data, dict):
        # Single object file: object slice is the entire content
        process_record(
            data,
            name,
            content,
            default_date_only,
            print_only_misses,
            is_first_record_in_file=True,
            object_text=content,
            object_start_line=1,
        )
    else:
        print(f"{name}, {default_date_only}, 1:DNL")
        print("")


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Extract Bible references from the 'verse' field. Robust unicode sanitation. On misses, logs the exact line within the same object to avoid duplicate misattribution."
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
        "filenames",
        nargs="*",
        help="One or more JSON file paths to process. If provided, directory scanning is skipped.",
    )
    args = ap.parse_args()

    default_date_only = utc_date_only_now()
    print_only_misses = args.print_only_misses

    if args.filenames:
        exit_code = 0
        for path in args.filenames:
            name = os.path.basename(path)
            if not os.path.isfile(path):
                print(f"Error: not a file or not found: {path}", file=sys.stderr)
                exit_code = 1
                continue
            process_file(path, name, default_date_only, print_only_misses)
        sys.exit(exit_code)

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
            os.path.join(base, name), name, default_date_only, print_only_misses
        )

    if files_seen == 0:
        print("No JSON files found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
