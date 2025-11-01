#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sys
import unicodedata
from typing import Any

# Remove only zero-width/BOM characters
ZERO_WIDTHS = "".join(
    [
        "\u200b",  # zero width space
        "\u200c",  # zero width non-joiner
        "\u200d",  # zero width joiner
        "\u2060",  # word joiner
        "\ufeff",  # BOM
    ]
)
ZW_RE = re.compile(f"[{re.escape(ZERO_WIDTHS)}]")

# Only normalize fullwidth parentheses to ASCII; do not touch JSON brackets/braces
PAREN_TRANSLATION = str.maketrans(
    {
        "\uff08": "(",  # FULLWIDTH (
        "\uff09": ")",  # FULLWIDTH )
    }
)


def sanitize_string(s: str) -> str:
    """
    Sanitize a JSON string value safely:
      - Unicode NFKC normalization
      - Remove zero-width/BOM characters anywhere
      - Normalize ONLY fullwidth parentheses to ASCII
      - Do NOT alter quotes, backslashes, or JSON syntax characters
    """
    t = unicodedata.normalize("NFKC", s)
    t = ZW_RE.sub("", t)
    t = t.translate(PAREN_TRANSLATION)
    return t


def sanitize_obj(obj: Any) -> Any:
    """
    Recursively sanitize string values in a parsed JSON object.
    Keys are left as-is (optional: sanitize keys if needed).
    """
    if isinstance(obj, str):
        return sanitize_string(obj)
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, dict):
        # keep keys as-is to avoid breaking consumer code that expects exact keys
        return {k: sanitize_obj(v) for k, v in obj.items()}
    return obj  # numbers, bool, None


def process_file(path: str, backup: bool, dry_run: bool) -> None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[error] read failed: {path}: {e}", file=sys.stderr)
        return

    # Parse JSON first to ensure validity
    try:
        data = json.loads(content)
    except Exception as e:
        print(f"[error] invalid JSON (skipped): {path}: {e}", file=sys.stderr)
        return

    sanitized = sanitize_obj(data)

    # Dump using json to keep valid structure; choose formatting you want
    new_text = json.dumps(sanitized, ensure_ascii=False, indent=2)
    new_text += "\n"

    if new_text == content or new_text.strip() == content.strip():
        print(f"[ok] no changes: {path}")
        return

    if dry_run:
        print(f"[dry-run] would update: {path}")
        return

    if backup:
        try:
            shutil.copy2(path, path + ".bak")
            print(f"[backup] {path}.bak")
        except Exception as e:
            print(f"[warn] backup failed: {path}: {e}", file=sys.stderr)

    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        print(f"[updated] {path}")
    except Exception as e:
        print(f"[error] write failed: {path}: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="Sanitize JSON files while preserving valid JSON: remove zero-width/BOM chars and normalize Unicode in STRING VALUES only."
    )
    ap.add_argument(
        "files",
        nargs="+",
        help="One or more JSON files (shell globs like *.json are expanded by your shell)",
    )
    ap.add_argument(
        "--backup", action="store_true", help="Write .bak backups before overwriting"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which files would change without writing",
    )
    args = ap.parse_args()

    for path in args.files:
        if not os.path.isfile(path):
            print(f"[skip] not a file: {path}", file=sys.stderr)
            continue
        process_file(path, backup=args.backup, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
