#!/usr/bin/env python3
"""
Normalize curly double quotes in selected JSON fields so that pairs are “opening” … ”closing”.

Scenario:
-  All quotes inside values are currently the left curly quote “
-  We want the closing quotes to be the right curly quote ”

Behavior:
-  Targets only fields: verse_text, prayer, reflection
-  Operates on raw JSON text (preserves formatting and other fields)
-  For each targeted JSON string value, scans left-to-right:
    Every occurrence of “ toggles between opening and closing:
      1st -> “, 2nd -> ”, 3rd -> “, 4th -> ”, ...
-  Leaves any existing right quotes ” unchanged (if any), but you can force-normalize if desired
-  Preview mode prints only what would change; update mode writes back to the same file

Usage:
    python3 pair_curly_quotes_in_values.py --preview *.json
    python3 pair_curly_quotes_in_values.py *.json
"""

import argparse
import os
import re
from typing import Tuple

TARGET_FIELDS = ("verse_text", "prayer", "reflection")
LEFT = "“"  # U+201C
RIGHT = "”"  # U+201D


def build_field_regex(field: str) -> re.Pattern:
    # Match: "field" : "value-with-escapes"
    key = re.escape(field)
    # JSON string literal pattern: "(escaped char or non-quote/backslash)*"
    pattern = rf'("{key}")\s*:\s*("(?:\\.|[^"\\])*")'
    return re.compile(pattern)


def normalize_quotes_in_literal(literal: str) -> Tuple[str, int]:
    """
    literal: JSON string literal including surrounding quotes.
    We do NOT unescape JSON. We work on the raw literal content.

    Rules:
    - Walk the inner text. For each actual left curly quote “, alternate:
        1st occurrence -> keep “
        2nd occurrence -> change to ”
        3rd -> “
        4th -> ”
        ...
    - Existing ” are left as-is (so already-correct closers remain correct)
    Returns (new_literal, number_of_replacements)
    """
    assert literal.startswith('"') and literal.endswith('"')
    inner = literal[1:-1]

    out = []
    replacements = 0
    expect_open = True  # True means next “ encountered is an opener (keep “), next should be closer (change to ”)

    i = 0
    while i < len(inner):
        ch = inner[i]

        # Preserve JSON escape sequences untouched (e.g., \" \\ \n \uXXXX)
        if ch == "\\":
            # Copy backslash and the next char (if any) verbatim
            if i + 1 < len(inner):
                out.append(inner[i])
                out.append(inner[i + 1])
                i += 2
                continue
            else:
                out.append(ch)
                i += 1
                continue

        if ch == LEFT:
            if expect_open:
                # Opening: keep LEFT
                out.append(LEFT)
                # Next expected is closing
                expect_open = False
            else:
                # Closing: convert LEFT -> RIGHT
                out.append(RIGHT)
                replacements += 1
                expect_open = True
            i += 1
            continue

        # If we encounter an existing RIGHT, keep it and reset expect_open to True (end of a pair)
        if ch == RIGHT:
            out.append(RIGHT)
            expect_open = True
            i += 1
            continue

        # Other characters as-is
        out.append(ch)
        i += 1

    new_literal = '"' + "".join(out) + '"'
    return new_literal, replacements


def process_file(path: str, preview: bool) -> int:
    raw = open(path, "r", encoding="utf-8").read()
    total_repl = 0
    header_printed = False

    for field in TARGET_FIELDS:
        pattern = build_field_regex(field)

        def repl(m: re.Match) -> str:
            nonlocal total_repl, header_printed
            key = m.group(1)  # "field"
            value = m.group(2)  # "...." JSON string literal
            new_value, cnt = normalize_quotes_in_literal(value)
            if cnt > 0:
                total_repl += cnt
                if preview and not header_printed:
                    print("\n" + "=" * 70)
                    print(f"FILE: {path}")
                    print("=" * 70)
                    header_printed = True
                if preview:
                    before_snip = value[:120].replace("\n", " ")
                    after_snip = new_value[:120].replace("\n", " ")
                    b_more = "…" if len(value) > 120 else ""
                    a_more = "…" if len(new_value) > 120 else ""
                    print(f"* {field}:")
                    print(f"    BEFORE: {before_snip}{b_more}")
                    print(f"    AFTER : {after_snip}{a_more}")
                return f"{key}: {new_value}"
            return m.group(0)

        raw = pattern.sub(repl, raw)

    if total_repl > 0 and not preview:
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)

    return total_repl


def main():
    ap = argparse.ArgumentParser(
        description="Normalize curly quotes in verse_text, prayer, reflection to “opening”/”closing” pairs."
    )
    ap.add_argument(
        "--preview", action="store_true", help="Preview changes without writing files"
    )
    ap.add_argument("files", nargs="+", help="JSON files to process (e.g., *.json)")
    args = ap.parse_args()

    total_files = 0
    total_changes = 0

    for path in args.files:
        if not os.path.exists(path):
            print(f"Warning: not found: {path}")
            continue
        try:
            cnt = process_file(path, args.preview)
            if not args.preview and cnt > 0:
                print(f"✔ Updated {path} ({cnt} closing quote fix(es))")
            total_changes += cnt
            total_files += 1
        except Exception as e:
            print(f"❌ Error processing {path}: {e}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"* Files processed: {total_files}")
    print(f"* Closing quotes fixed: {total_changes}")
    print(f"* Mode: {'PREVIEW' if args.preview else 'UPDATE'}")


if __name__ == "__main__":
    main()
