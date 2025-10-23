#!/usr/bin/env python3
import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Configuration
INPUT_DIR = Path("missing")  # folder with your saved Gmail .txt messages
OUT_IDS = Path("matching_ids.txt")
OUT_CSV = Path("matched_messages.csv")
OUT_JSON = Path("matched_messages.json")

# Markers from your saved export
HDR_BODY_SEP = "=" * 67
BODY_HEADER_RE = re.compile(
    rf"^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*",
    re.MULTILINE,
)

# A heading line is any non-empty line that ends with a colon
HEADING_LINE_RE = re.compile(r"^\s*(?P<h>[^:\n\r]+?)\s*:\s*$")

# Position matchers (case-insensitive, flexible)
POS1_RE = re.compile(r"\bverses?\b", re.IGNORECASE)  # verse/verses
POS2_RE = re.compile(
    r"\b(thoughts?|lessons?)\b", re.IGNORECASE
)  # thought(s) / lesson(s)
POS3_RE = re.compile(r"\bprayers?\b", re.IGNORECASE)  # prayer(s)

# Optional terminator for prayer when slicing content in some formats (not required here)
PRAYER_TERMINATOR = "Pastor Alvin and Marcie Sather"


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


def extract_header_fields(full_text: str) -> Dict[str, str]:
    hdr = {"message_id": "", "subject": "", "from": "", "to": "", "date": ""}
    for line in full_text.splitlines():
        if line.startswith("message_id: "):
            hdr["message_id"] = line.split("message_id: ", 1)[1].strip()
        elif line.startswith("subject   : "):
            hdr["subject"] = line.split("subject   : ", 1)[1].strip()
        elif line.startswith("from      : "):
            hdr["from"] = line.split("from      : ", 1)[1].strip()
        elif line.startswith("to        : "):
            hdr["to"] = line.split("to        : ", 1)[1].strip()
        elif line.startswith("date      : "):
            hdr["date"] = line.split("date      : ", 1)[1].strip()
        if line.strip() == HDR_BODY_SEP:
            break
    return hdr


def extract_body(full_text: str) -> str:
    m = BODY_HEADER_RE.search(full_text)
    if m:
        return full_text[m.end() :].strip()
    parts = full_text.split(HDR_BODY_SEP)
    if len(parts) >= 3:
        return (HDR_BODY_SEP.join(parts[2:])).strip()
    return full_text.strip()


def first_three_headings(body: str) -> List[Tuple[int, str]]:
    """
    Return list of (line_index, heading_without_colon) for the first three heading lines.
    """
    body_norm = normalize(body)
    lines = body_norm.splitlines()
    found: List[Tuple[int, str]] = []
    for idx, ln in enumerate(lines):
        if HEADING_LINE_RE.match(ln):
            h = ln.rstrip()
            if h.endswith(":"):
                h = h[:-1].rstrip()
            found.append((idx, h))
            if len(found) == 3:
                break
    return found


def find_terminator_index(lines: List[str], terminator: str) -> Optional[int]:
    term = normalize(terminator).lower()
    for i, ln in enumerate(lines):
        if normalize(ln).lower() == term:
            return i
    return None


def slice_sections_by_positions(
    body: str, pos: List[Tuple[int, str]]
) -> Dict[str, str]:
    """
    Given body and heading positions [(idx, heading_text), ...] for up to 3 headings,
    slice verse (1), reflection (2), prayer (3). Include text after tag line until next tag or terminator (for prayer).
    """
    body_norm = normalize(body)
    lines = body_norm.splitlines()
    verse = reflection = prayer = ""

    if len(pos) >= 1:
        i1 = pos[0][0]
        stop = pos[1][0] if len(pos) >= 2 else len(lines)
        # content starts from same line after the tag? we conservatively take from next line
        verse = "\n".join(lines[i1 + 1 : stop]).strip()

    if len(pos) >= 2:
        i2 = pos[1][0]
        stop = pos[2][0] if len(pos) >= 3 else len(lines)
        reflection = "\n".join(lines[i2 + 1 : stop]).strip()

    if len(pos) >= 3:
        i3 = pos[2][0]
        term_idx = find_terminator_index(lines, PRAYER_TERMINATOR)
        stop_candidates = [len(lines)]
        if term_idx is not None:
            stop_candidates.append(term_idx)
        stop = min(stop_candidates)
        prayer = "\n".join(lines[i3 + 1 : stop]).strip()

    return {"verse": verse, "reflection": reflection, "prayer": prayer}


def headings_match_positional(first3: List[Tuple[int, str]]) -> bool:
    """
    Apply positional rules:
      pos1: contains verse
      pos2: contains thought or lesson
      pos3: contains prayer
    """
    if len(first3) < 3:
        return False
    _, h1 = first3[0]
    _, h2 = first3[1]
    _, h3 = first3[2]
    return bool(POS1_RE.search(h1) and POS2_RE.search(h2) and POS3_RE.search(h3))


def main():
    files = sorted(INPUT_DIR.glob("*.txt"))
    if not files:
        print(f"No .txt files found in {INPUT_DIR.resolve()}")
        return

    matching_ids: List[str] = []
    rows: List[Dict[str, str]] = []

    total = len(files)
    matches = 0

    for i, fp in enumerate(files, 1):
        txt = fp.read_text(encoding="utf-8", errors="replace")
        hdr = extract_header_fields(txt)
        body = extract_body(txt)

        first3 = first_three_headings(body)
        if headings_match_positional(first3):
            matches += 1
            # Collect message_id
            mid = hdr.get("message_id", "")
            matching_ids.append(mid)

            # Slice sections
            sections = slice_sections_by_positions(body, first3)

            rows.append(
                {
                    "message_id": mid,
                    "date_utc": hdr.get("date", ""),
                    "subject": hdr.get("subject", ""),
                    "verse": sections["verse"],
                    "reflection": sections["reflection"],
                    "prayer": sections["prayer"],
                    "reading": "",  # optional field, left empty for now
                    "original_content": normalize(body),
                }
            )

        if i % 200 == 0 or i == total:
            print(f"Scanned {i}/{total} files...")

    print("\nSummary:")
    print(f"- Total files scanned: {total}")
    print(f"- Files matching positional rule (verse/thought|lesson/prayer): {matches}")

    # Write outputs
    OUT_IDS.write_text(
        "\n".join(matching_ids) + ("\n" if matching_ids else ""), encoding="utf-8"
    )
    print(f"Wrote IDs: {OUT_IDS.resolve()} ({len(matching_ids)} ids)")

    if rows:
        with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "message_id",
                    "date_utc",
                    "subject",
                    "verse",
                    "reflection",
                    "prayer",
                    "reading",
                    "original_content",
                ],
            )
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote CSV: {OUT_CSV.resolve()} ({len(rows)} rows)")

        with OUT_JSON.open("w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        print(f"Wrote JSON: {OUT_JSON.resolve()} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
