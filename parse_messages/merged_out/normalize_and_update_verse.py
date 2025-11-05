#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------- Configuration ---------------

# Field names
VERSE_FIELD = "verse"
BACKUP_FIELD = "original_verse_raw"  # where to store the pre-normalized value
PRESERVED_ABC_FIELD = "verse_with_abc"  # only used when --preserve-abc is set

# Known book name fixes (case-insensitive keys)
BOOK_FIXES = {
    "matth": "Matthew",
    "matt": "Matthew",
    "jn": "John",
    "jhn": "John",
    "ps": "Psalm",
    "psa": "Psalm",
    "psalm": "Psalm",
    "psalms": "Psalm",
    "prov": "Proverbs",
    "song of songs": "Song of Solomon",
    "song of solomon": "Song of Solomon",
    "songs": "Song of Solomon",
    "1cor": "1 Corinthians",
    "2cor": "2 Corinthians",
    "1thes": "1 Thessalonians",
    "2thes": "2 Thessalonians",
    "1tim": "1 Timothy",
    "2tim": "2 Timothy",
    "1pet": "1 Peter",
    "2pet": "2 Peter",
    "1john": "1 John",
    "2john": "2 John",
    "3john": "3 John",
    "rev": "Revelation",
    "heb": "Hebrews",
    "rom": "Romans",
    "gal": "Galatians",
    "eph": "Ephesians",
    "phil": "Philippians",
    "col": "Colossians",
    "tit": "Titus",
    "philem": "Philemon",
    "gen": "Genesis",
    "ex": "Exodus",
    "deut": "Deuteronomy",
    "eccl": "Ecclesiastes",
    "lam": "Lamentations",
    # Add more as needed
}

# --------------- Regex helpers ---------------

REF_SPLIT_RE = re.compile(r"\s*,\s*")  # split comma-separated verse tokens
PART_SUFFIX_RE = re.compile(r"^(\d+)([abc])$", re.IGNORECASE)
BOOK_CHAPTER_RE = re.compile(
    r"^\s*(?P<book>[\dA-Za-z ]+?)\s+(?P<chapter>\d+):(?P<rest>.+?)\s*$"
)
TRAILING_JUNK_RE = re.compile(
    r"""[\'\"\.\s]+$"""
)  # strip trailing quotes/periods/spaces per token

# --------------- Normalization core ---------------


def fix_book_name(raw_book: str) -> str:
    s = " ".join(raw_book.split()).strip()
    key = s.lower()
    return BOOK_FIXES.get(key, s)


def strip_part_suffix(token: str) -> Tuple[str, Optional[str]]:
    """
    Strip trailing a/b/c from a verse token if present.
    Returns (numeric_part, suffix or None)
    """
    token = token.strip()
    m = PART_SUFFIX_RE.match(token)
    if m:
        return m.group(1), m.group(2).lower()
    return token, None


def clean_token_strip_abc(token: str) -> str:
    """
    Clean a verse token for normalized output (strips a/b/c):
      - Remove trailing quotes/periods/spaces
      - Strip partial suffix (a/b/c)
      - Validate numeric or range
    Returns cleaned token, raises ValueError if invalid.
    """
    t = TRAILING_JUNK_RE.sub("", token.strip())
    if not t:
        raise ValueError(f"Empty verse token after cleaning from {token!r}")
    if "-" in t:
        if t.count("-") != 1:
            raise ValueError(f"Invalid range (multiple hyphens) in token {token!r}")
        a, b = t.split("-", 1)
        a_num, _ = strip_part_suffix(a)
        b_num, _ = strip_part_suffix(b)
        if not a_num.isdigit() or not b_num.isdigit():
            raise ValueError(f"Range endpoints must be numeric in token {token!r}")
        if int(a_num) > int(b_num):
            raise ValueError(f"Range start > end in token {token!r}")
        return f"{int(a_num)}-{int(b_num)}"
    else:
        v, _ = strip_part_suffix(t)
        if not v.isdigit():
            raise ValueError(f"Verse number must be numeric in token {token!r}")
        return str(int(v))


def clean_token_keep_abc(token: str) -> str:
    """
    Clean a verse token but keep a/b/c suffix if present.
    """
    t = TRAILING_JUNK_RE.sub("", token.strip())
    if not t:
        raise ValueError(f"Empty verse token after cleaning from {token!r}")
    if "-" in t:
        if t.count("-") != 1:
            raise ValueError(f"Invalid range (multiple hyphens) in token {token!r}")
        a, b = t.split("-", 1)
        a_num, a_suf = strip_part_suffix(a)
        b_num, b_suf = strip_part_suffix(b)
        if not a_num.isdigit() or not b_num.isdigit():
            raise ValueError(f"Range endpoints must be numeric in token {token!r}")
        if int(a_num) > int(b_num):
            raise ValueError(f"Range start > end in token {token!r}")
        # Keep suffix on right endpoint only (conventional)
        right = f"{int(b_num)}{b_suf or ''}"
        return f"{int(a_num)}-{right}"
    else:
        v, suf = strip_part_suffix(t)
        if not v.isdigit():
            raise ValueError(f"Verse number must be numeric in token {token!r}")
        return f"{int(v)}{suf or ''}"


def normalize_reference(ref_line: str, keep_abc: bool = False) -> str:
    """
    Normalize to: 'Book Chapter:verses'
    - Fix book name using BOOK_FIXES
    - Collapse spaces
    - Support comma-separated tokens and hyphenated ranges
    - Clean trailing quotes/dots inside tokens
    - Either strip a/b/c (default) or keep them (keep_abc=True)
    Raises ValueError on errors.
    """
    if ref_line is None:
        raise ValueError("Reference is None")
    s = ref_line.strip().strip('"').strip("'").strip()
    if not s:
        raise ValueError("Reference is empty")

    m = BOOK_CHAPTER_RE.match(s)
    if not m:
        raise ValueError(f"Cannot parse book/chapter/verses from: {ref_line!r}")

    book = fix_book_name(m.group("book"))
    chapter = m.group("chapter").strip()
    rest = m.group("rest").strip()
    if not rest:
        raise ValueError(f"No verse component after chapter in: {ref_line!r}")

    parts = [p for p in REF_SPLIT_RE.split(rest) if p.strip()]
    if not parts:
        raise ValueError(f"No verse parts detected in: {ref_line!r}")

    if keep_abc:
        cleaned_parts: List[str] = [clean_token_keep_abc(p) for p in parts]
    else:
        cleaned_parts = [clean_token_strip_abc(p) for p in parts]

    return f"{book} {int(chapter)}:{','.join(cleaned_parts)}"


# --------------- File processing ---------------


def load_json_records(
    data: Any, filename: Path
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    if isinstance(data, list):
        return data, None, None
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            return data[list_keys[0]], data, list_keys[0]
        raise ValueError(
            f"{filename}: expected a list or a dict with a single list of records"
        )
    raise ValueError(f"{filename}: unsupported JSON structure")


def main():
    parser = argparse.ArgumentParser(
        description='Normalize and overwrite the "verse" field in JSON files.'
    )
    parser.add_argument(
        "files", nargs="+", help="One or more JSON files (e.g., *.json)"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show changes without writing files (fail-fast).",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="In preview, log errors but continue.",
    )
    parser.add_argument(
        "--preserve-abc",
        action="store_true",
        help=f"Also write a {PRESERVED_ABC_FIELD} that keeps a/b/c specifiers.",
    )
    parser.add_argument(
        "--backup-field",
        default=BACKUP_FIELD,
        help=f"Backup field name (default: {BACKUP_FIELD})",
    )
    args = parser.parse_args()

    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f"[ERROR] Not found: {path}")
            sys.exit(2)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            records, container, key = load_json_records(raw, path)
        except Exception as e:
            print(f"[ERROR] {path}: cannot read/parse JSON: {e}")
            sys.exit(2)

        changes: List[Dict[str, str]] = []
        updated_records: List[Dict[str, Any]] = []

        for idx, rec in enumerate(records, start=1):
            if not isinstance(rec, dict):
                changes.append({"_note": "skipped non-object"})
                updated_records.append(rec)
                continue

            rec_copy = dict(rec)
            change: Dict[str, str] = {}

            value = rec_copy.get(VERSE_FIELD)
            if isinstance(value, str) and value.strip():
                original = value
                try:
                    normalized = normalize_reference(original, keep_abc=False)
                    if args.preserve - abc:
                        normalized_with_abc = normalize_reference(
                            original, keep_abc=True
                        )
                    else:
                        normalized_with_abc = None
                except ValueError as e:
                    msg = f"{path}:{idx} invalid {VERSE_FIELD}: {e}"
                    if args.preview and not args.continue_on_error:
                        print(f"[ERROR] {msg}")
                        sys.exit(2)
                    else:
                        print(f"[ERROR] {msg}")
                        changes.append({"error": str(e)})
                        updated_records.append(rec_copy)
                        continue

                # Backup original if not already present
                if args.backup_field not in rec_copy:
                    rec_copy[args.backup_field] = original
                    change[args.backup_field] = original

                # Overwrite verse with normalized (no a/b/c)
                if rec_copy.get(VERSE_FIELD) != normalized:
                    rec_copy[VERSE_FIELD] = normalized
                    change[VERSE_FIELD] = normalized

                # Optionally store preserved-abc version
                if args.preserve - abc and normalized_with_abc:
                    rec_copy[PRESERVED_ABC_FIELD] = normalized_with_abc
                    change[PRESERVED_ABC_FIELD] = normalized_with_abc

            else:
                # No verse or empty; skip
                change["_note"] = "no verse field or empty"

            updated_records.append(rec_copy)
            changes.append(change if change else {"_note": "no changes"})

        if args.preview:
            print(f"\n=== Preview: {path} ===")
            sep = "=" * 50
            for i, change in enumerate(changes, start=1):
                print(sep)
                print(f"Record {i}:")
                for k, v in change.items():
                    print(f"- {k}: {v}")
            print(sep)
            continue

        # Write back
        try:
            if container is None:
                out = updated_records
            else:
                container[key] = updated_records
                out = container
            path.write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[OK] Updated: {path}")
        except Exception as e:
            print(f"[ERROR] {path}: failed to write output: {e}")
            sys.exit(2)


if __name__ == "__main__":
    main()
