#!/usr/bin/env python3
import json
import os
import re
import sys
import shutil
from typing import Dict, Tuple, Optional

# Default fields to process
DEFAULT_FIELDS = ["subject", "verse", "reflection", "prayer", "reading"]

# Map abbreviation -> full name (case-sensitive)
ABBR_TO_FULL = {
    "Ps": "Psalms",
    "Ro": "Romans",
    "Jer": "Jeremiah",
    "Heb": "Hebrews",
    "Rev": "Revelation",
    "Phil": "Philippians",
    "Isa": "Isaiah",
    "Mt": "Matthew",
    "Pet": "Peter",
    "Cor": "Corinthians",
    "Pro": "Proverbs",
    "Jn": "John",
    "Dan": "Daniel",
    "Ex": "Exodus",
    "Chro": "Chronicles",
    "Chron": "Chronicles",
    "Mk": "Mark",
    "Lk": "Luke",
    "Gen": "Genesis",
    "Gal": "Galatians",
    "Col": "Colossians",
    "Thess": "Thessalonians",
    "Lam": "Lamentations",
    "Eccl": "Ecclesiastes",
    "Jm": "James",
}

# Build combined regex: whole-word abbr with optional dot and optional space
ABBR_ALT = "|".join(sorted(map(re.escape, ABBR_TO_FULL.keys()), key=len, reverse=True))
PATTERN = re.compile(rf"\b(?P<abbr>{ABBR_ALT})(?P<dot>\.)?(?P<sp>\s?)\b")
DIGITS_AHEAD = re.compile(r"^\s*\d")

SEPARATOR = "=" * 72  # section break


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return json.loads(content), content
    except Exception:
        return None, None


def write_json_file(path: str, data) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return text


def find_line_number_for_field(content: str, key: str, value: str) -> int:
    for i, line in enumerate(content.splitlines(), start=1):
        if f'"{key}"' in line:
            return i
    return 1


def replace_match(m: re.Match) -> str:
    abbr = m.group("abbr")
    full = ABBR_TO_FULL.get(abbr, abbr)
    following = m.string[m.end() :]
    needs_space = bool(DIGITS_AHEAD.match(following))
    return f"{full} " if needs_space else full


def value_match_snippet(value: str, context: int = 40) -> str:
    m = PATTERN.search(value)
    if not m:
        return (value[: context * 2]).replace("\n", " ")
    start = max(0, m.start() - context)
    end = min(len(value), m.end() + context)
    snippet = value[start:end].replace("\n", " ")
    if start > 0:
        snippet = "..." + snippet
    if end < len(value):
        snippet = snippet + "..."
    return snippet


def preview_after(text: str) -> str:
    return PATTERN.sub(replace_match, text)


def prompt_yes_no(question: str) -> bool:
    while True:
        ans = input(f"{question} [y/n/q]: ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        if ans in ("q", "quit"):
            print("Aborting by user request.")
            sys.exit(1)
        print("Please answer y, n, or q.")


def process_file(path: str, mode: str, fields_to_use) -> Tuple[int, int]:
    """
    Process one file.
    mode: 'interactive' | 'count' | 'yes'
    Returns (replacements_in_file, fields_changed)
    """
    data, content = read_json_file(path)
    if data is None:
        return 0, 0

    name = os.path.basename(path)
    changed = False
    file_repl = 0
    fields_changed = 0

    def handle_field(obj: Dict, key: str):
        nonlocal changed, file_repl, fields_changed
        val = obj.get(key)
        if not isinstance(val, str):
            return
        if not PATTERN.search(val):
            return

        # Count how many would change
        _, cnt_preview = PATTERN.subn(replace_match, val)

        if mode == "count":
            print(f"{name}:{key}: {cnt_preview}")
            file_repl += cnt_preview
            if cnt_preview > 0:
                fields_changed += 1
            return

        line = find_line_number_for_field(content, key, val)

        if mode == "interactive":
            print(SEPARATOR)
            print(f"file  : {name}:{line}")
            print(f"field : {key}")
            print(f"snippet:")
            print(f"    {value_match_snippet(val)}")
            print()
            print(f"after:")
            print(f"    {preview_after(val)}")
            print(f"code  : code -g {name}:{line}")

            if prompt_yes_no("Apply replacements in this field?"):
                new_val, cnt = PATTERN.subn(replace_match, val)
                if cnt > 0:
                    obj[key] = new_val
                    changed = True
                    file_repl += cnt
                    fields_changed += 1
                    print(f"Applied {cnt} replacement(s) in {key}.")
            return

        if mode == "yes":
            new_val, cnt = PATTERN.subn(replace_match, val)
            if cnt > 0:
                obj[key] = new_val
                changed = True
                file_repl += cnt
                fields_changed += 1
            return

    if isinstance(data, list):
        for item in data:
            if isinstance(item, Dict):
                for f in fields_to_use:
                    handle_field(item, f)
    elif isinstance(data, Dict):
        for f in fields_to_use:
            handle_field(data, f)

    if changed and mode in ("interactive", "yes"):
        shutil.copy2(path, path + ".bak")
        write_json_file(path, data)
        print(
            f"Updated {name} (+{file_repl} replacements in {fields_changed} field(s))"
        )

    return file_repl, fields_changed


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Normalize Bible book abbreviations to full names in JSON fields."
    )
    group = ap.add_mutually_exclusive_group()
    group.add_argument(
        "--count",
        action="store_true",
        help="Count replacements only (no prompts, no changes)",
    )
    group.add_argument(
        "--yes", action="store_true", help="Apply all replacements without prompting"
    )
    ap.add_argument(
        "--fields",
        nargs="*",
        default=DEFAULT_FIELDS,
        help="Fields to check (default: subject verse reflection prayer reading)",
    )
    args = ap.parse_args()

    fields_to_use = args.fields

    base = script_dir()
    any_json = False
    grand_total = 0
    files_changed = 0
    fields_changed_total = 0

    mode = "count" if args.count else ("yes" if args.yes else "interactive")

    for name in sorted(os.listdir(base)):
        if not name.endswith(".json"):
            continue
        any_json = True
        path = os.path.join(base, name)
        file_repl, fields_changed = process_file(path, mode, fields_to_use)
        grand_total += file_repl
        fields_changed_total += fields_changed
        if file_repl > 0 and mode in ("interactive", "yes"):
            files_changed += 1

    if not any_json:
        print("No JSON files found", file=sys.stderr)
        sys.exit(1)

    # Summary
    if args.count:
        print(SEPARATOR)
        print(f"Total replacements: {grand_total}")
        print(f"Fields affected:    {fields_changed_total}")

    if args.yes:
        print(SEPARATOR)
        print(f"Applied replacements: {grand_total}")
        print(f"Files updated:        {files_changed}")
        print(f"Fields updated:       {fields_changed_total}")


if __name__ == "__main__":
    main()
