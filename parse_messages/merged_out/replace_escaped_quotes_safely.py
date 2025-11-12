#!/usr/bin/env python3
"""
Safely replace only the exact backslash+quote sequence (\") with a left smart quote (“)
inside string values of the fields: verse_text, prayer, reflection.

-  Operates on raw file text to avoid reformatting or touching other fields.
-  Only changes occurrences inside the value of those fields.
-  Leaves everything else (spacing, ordering, other fields) intact.

Usage:
    python3 replace_escaped_quotes_safely.py --preview *.json
    python3 replace_escaped_quotes_safely.py *.json
"""

import argparse
import os
import re
from typing import Tuple

# Target fields
TARGET_FIELDS = ("verse_text", "prayer", "reflection")
LEFT_SMART_QUOTE = "“"


# Regex that finds a JSON string field by name and captures the raw quoted value (with escapes)
# Key rules:
#   - match JSON string key: "key"
#   - optional whitespace, colon, optional whitespace
#   - capture the value string as a JSON string starting with " and ending at the matching "
#   - handle escaped quotes and backslashes within the value
#
# This pattern: ("key")\s*:\s*(" ... ")
# Where the value " ... " is matched by \" (escaped quote) or \\ (escaped backslash) or [^"\\] (any other char)
def build_field_regex(field: str) -> re.Pattern:
    key = re.escape(field)
    pattern = rf'("{key}")\s*:\s*("(?:\\.|[^"\\])*")'
    return re.compile(pattern)


# Replace only unescaped \" within a JSON-quoted string literal
def replace_escaped_quotes_in_json_string_literal(literal: str) -> Tuple[str, int]:
    """
    literal: a JSON string literal including surrounding quotes, e.g. "some \"text\" here"
    Returns: (new_literal, replacements_count)
    Only replaces occurrences of backslash+quote inside the literal content.
    """
    assert literal.startswith('"') and literal.endswith('"')
    inner = literal[1:-1]

    # We want to replace occurrences of \" that are not themselves escaped (i.e., not \\\" as the backslash)
    # But in JSON string content, a backslash is escaped as \\ in the raw file. Here we are still in the raw file context.
    #
    # Strategy: walk the string and when we see a backslash that escapes a quote, replace the pair \" with the UTF-8 smart quote,
    # but we must encode the smart quote as-is (no backslash) inside the JSON string; JSON allows unicode chars directly.
    #
    # Careful with sequences like \\" (escaped backslash + quote). In raw text it's two chars backslash+backslash then quote.
    # We only replace when the backslash directly escapes the quote (i.e., a single backslash before " that is not itself escaped).

    chars = []
    i = 0
    replacements = 0
    while i < len(inner):
        c = inner[i]
        if c == "\\":
            # Count preceding consecutive backslashes including this one
            # If we see a backslash and the next char is ", and the number of consecutive backslashes before the quote is odd,
            # then this backslash escapes the quote.
            j = i
            while j < len(inner) and inner[j] == "\\":
                j += 1
            backslashes_count = j - i
            next_char = inner[j] if j < len(inner) else ""
            if next_char == '"' and backslashes_count % 2 == 1:
                # Replace the pair (a single escaping backslash + ") with the smart quote,
                # and keep any additional preceding backslashes beyond the escaping one.
                # E.g., for "\\\"" (two backslashes + quote), the sequence represents: escaped backslash + escaped quote.
                # Backslashes_count may be 1,3,5,... If it's 1, we replace \" with “
                # If it's 3, it's \\\" where two backslashes produce a literal \ and one escapes the quote.
                # We keep backslashes_count - 1 literal backslashes, then emit the smart quote.
                literal_bslashes_to_keep = backslashes_count - 1
                chars.extend("\\" * literal_bslashes_to_keep)
                chars.append(LEFT_SMART_QUOTE)
                replacements += 1
                i = j + 1  # skip the quote too
                continue
            else:
                # Not an escaping backslash for a quote; copy the backslashes
                chars.extend("\\" * backslashes_count)
                i = j
                continue
        # Normal char path
        chars.append(c)
        i += 1

    new_inner = "".join(chars)
    return f'"{new_inner}"', replacements


def process_file(path: str, preview: bool) -> int:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    total_changes = 0
    any_header_printed = False

    # For each target field, apply replacements on its value string(s)
    for field in TARGET_FIELDS:
        pattern = build_field_regex(field)

        # We will rebuild the file with re.sub using a function that transforms only the value literal
        def repl(m: re.Match) -> str:
            nonlocal total_changes, any_header_printed
            key = m.group(1)  # "field"
            value_lit = m.group(2)  # "...." (raw JSON string with escapes)

            new_value_lit, count = replace_escaped_quotes_in_json_string_literal(
                value_lit
            )
            if count > 0:
                total_changes += count
                if preview and not any_header_printed:
                    print("\n" + "=" * 70)
                    print(f"FILE: {path}")
                    print("=" * 70)
                    any_header_printed = True
                if preview:
                    # Print a short diff-like view
                    before_snip = value_lit[:80].replace("\n", " ")
                    after_snip = new_value_lit[:80].replace("\n", " ")
                    suffix_b = "…" if len(value_lit) > 80 else ""
                    suffix_a = "…" if len(new_value_lit) > 80 else ""
                    print(f"* {field}:")
                    print(f"    BEFORE: {before_snip}{suffix_b}")
                    print(f"    AFTER : {after_snip}{suffix_a}")
                return f"{key}: {new_value_lit}"
            else:
                return m.group(0)

        raw = pattern.sub(repl, raw)

    if total_changes > 0 and not preview:
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)

    return total_changes


def main():
    ap = argparse.ArgumentParser(
        description='Safely replace \\" with “ in verse_text, prayer, reflection values.'
    )
    ap.add_argument(
        "--preview",
        action="store_true",
        help="Show only what would change; do not write files",
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
            changes = process_file(path, args.preview)
            if not args.preview and changes > 0:
                print(f"✔ Updated {path} ({changes} replacement(s))")
            total_changes += changes
            total_files += 1
        except Exception as e:
            print(f"❌ Error processing {path}: {e}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"* Files processed: {total_files}")
    print(f"* Replacements  : {total_changes}")
    print(f"* Mode          : {'PREVIEW' if args.preview else 'UPDATE'}")


if __name__ == "__main__":
    main()
