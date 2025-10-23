#!/usr/bin/env python3
import re
import unicodedata
from pathlib import Path
from typing import List

INPUT_DIR = Path("missing")  # folder with your saved message .txt files

HDR_BODY_SEP = "=" * 67
BODY_HEADER_RE = re.compile(
    rf"^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*",
    re.MULTILINE,
)

# A heading line is any non-empty line that ends with a colon
HEADING_LINE_RE = re.compile(r"^\s*(?P<h>[^:\n\r]+?)\s*:\s*$")


# Normalize function for robust matching
def normalize(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'").replace("´", "'")
    s = (
        s.replace("\u00a0", " ")
        .replace("\u2007", " ")
        .replace("\u202f", " ")
        .replace("\u00ad", "")
    )
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def extract_body(full_text: str) -> str:
    m = BODY_HEADER_RE.search(full_text)
    if m:
        return full_text[m.end() :].strip()
    parts = full_text.split(HDR_BODY_SEP)
    if len(parts) >= 3:
        return (HDR_BODY_SEP.join(parts[2:])).strip()
    return full_text.strip()


def first_three_headings(body: str) -> List[str]:
    body_norm = normalize(body)
    lines = body_norm.splitlines()
    found: List[str] = []
    for ln in lines:
        if HEADING_LINE_RE.match(ln):
            # Keep the heading text (without trailing colon)
            h = ln.rstrip()
            if h.endswith(":"):
                h = h[:-1].rstrip()
            found.append(h)
            if len(found) == 3:
                break
    return found


# Position matchers (case-insensitive, flexible)
POS1_RE = re.compile(
    r"\bvers(e|es|o|a)?\b", re.IGNORECASE
)  # catches verse, verses (allow minor typos)
POS2_RE = re.compile(r"\b(thought|thoughts|lesson|lessons)\b", re.IGNORECASE)
POS3_RE = re.compile(r"\bprayer(s)?\b", re.IGNORECASE)


def main():
    files = sorted(INPUT_DIR.glob("*.txt"))
    if not files:
        print(f"No .txt files found in {INPUT_DIR.resolve()}")
        return

    total = len(files)
    match_pos1 = match_pos2 = match_pos3 = 0
    match_all = 0
    examples_all: List[str] = []

    for i, fp in enumerate(files, 1):
        text = fp.read_text(encoding="utf-8", errors="replace")
        body = extract_body(text)
        headings = first_three_headings(body)  # [pos1, pos2, pos3] if present

        p1_ok = p2_ok = p3_ok = False
        if len(headings) >= 1 and POS1_RE.search(headings[0]):
            match_pos1 += 1
            p1_ok = True
        if len(headings) >= 2 and POS2_RE.search(headings[1]):
            match_pos2 += 1
            p2_ok = True
        if len(headings) >= 3 and POS3_RE.search(headings[2]):
            match_pos3 += 1
            p3_ok = True

        if p1_ok and p2_ok and p3_ok:
            match_all += 1
            if len(examples_all) < 10:
                examples_all.append(fp.name)

        if i % 200 == 0 or i == total:
            print(f"Scanned {i}/{total} files...")

    print("\nResults (read-only):")
    print(f"- Total files scanned: {total}")
    print(f"- Position 1 matched (verse variants): {match_pos1}")
    print(f"- Position 2 matched (thought/lesson variants): {match_pos2}")
    print(f"- Position 3 matched (prayer variants): {match_pos3}")
    print(f"- Files matching all three positions: {match_all}")
    if examples_all:
        print("Examples (first up to 10):")
        for ex in examples_all:
            print(f"  - {ex}")


if __name__ == "__main__":
    main()
