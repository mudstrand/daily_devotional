#!/usr/bin/env python3
import argparse
import os
import re
import sys
import unicodedata
import shutil

# Zero-width / BOM characters to remove anywhere in text
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

# Map a wide set of lookalike parentheses/brackets to ASCII ()
PAREN_TRANSLATION = {
    "\uff08": "(",  # FULLWIDTH (
    "\uff09": ")",  # FULLWIDTH )
    "\u2768": "(",  # MEDIUM LEFT PARENTHESIS ORNAMENT
    "\u2769": ")",  # MEDIUM RIGHT PARENTHESIS ORNAMENT
    "\u2772": "(",  # LIGHT LEFT TORTOISE SHELL BRACKET ORNAMENT
    "\u2773": ")",  # LIGHT RIGHT TORTOISE SHELL BRACKET ORNAMENT
    "\u3014": "(",  # LEFT TORTOISE SHELL BRACKET
    "\u3015": ")",  # RIGHT TORTOISE SHELL BRACKET
    "\u3010": "(",  # LEFT BLACK LENTICULAR BRACKET
    "\u3011": ")",  # RIGHT BLACK LENTICULAR BRACKET
    "\u207d": "(",  # SUPERSCRIPT (
    "\u207e": ")",  # SUPERSCRIPT )
    "\u208d": "(",  # SUBSCRIPT (
    "\u208e": ")",  # SUBSCRIPT )
}


def normalize_parens(s: str) -> str:
    s2 = s.translate(str.maketrans(PAREN_TRANSLATION))
    out = []
    for ch in s2:
        if ch in ("(", ")"):
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat == "Ps":
            out.append("(")
        elif cat == "Pe":
            out.append(")")
        else:
            out.append(ch)
    return "".join(out)


def sanitize_text(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    s = unicodedata.normalize("NFKC", text)
    s = ZW_RE.sub("", s)
    s = normalize_parens(s)
    return s


def sanitize_file(path: str, backup: bool) -> None:
    if not os.path.isfile(path):
        print(f"[skip] not a file: {path}", file=sys.stderr)
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception as e:
        print(f"[error] read failed: {path}: {e}", file=sys.stderr)
        return

    sanitized = sanitize_text(original)
    if sanitized == original:
        print(f"[ok] no changes: {path}")
        return

    if backup:
        bak = path + ".bak"
        try:
            shutil.copy2(path, bak)
            print(f"[backup] {bak}")
        except Exception as e:
            print(f"[warn] backup failed for {path}: {e}", file=sys.stderr)

    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(sanitized)
        print(f"[updated] {path}")
    except Exception as e:
        print(f"[error] write failed: {path}: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="Sanitize JSON files in-place: strip zero-width/BOMs, normalize Unicode (NFKC), and normalize parentheses/brackets to ASCII ()."
    )
    ap.add_argument(
        "files",
        nargs="+",
        help="One or more JSON file paths (shell globs like *.json are supported)",
    )
    ap.add_argument(
        "--backup",
        action="store_true",
        help="Write a .bak backup before overwriting each file",
    )
    args = ap.parse_args()

    for path in args.files:
        sanitize_file(path, backup=args.backup)


if __name__ == "__main__":
    main()
