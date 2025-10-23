#!/usr/bin/env python3
import csv
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple

# Configuration
INPUT_DIR = Path("missing")  # folder with your saved Gmail .txt messages
OUT_UNIQUE_POS1 = Path("unique_headings_pos1.csv")
OUT_UNIQUE_POS2 = Path("unique_headings_pos2.csv")
OUT_UNIQUE_POS3 = Path("unique_headings_pos3.csv")
OUT_SAMPLE_MAP = Path(
    "headings_by_file_sample.csv"
)  # optional sample mapping (file -> first three headings)

# Markers from your saved export
HDR_BODY_SEP = "=" * 67
BODY_HEADER_RE = re.compile(
    rf"^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*",
    re.MULTILINE,
)

# A "heading line" is any non-empty line that ends with a colon.
HEADING_LINE_RE = re.compile(r"^\s*(?P<h>[^:\n\r]+?)\s*:\s*$")


def normalize_for_compare(s: str) -> str:
    """
    Normalize for robust comparison:
    - Unicode NFKC
    - normalize apostrophes/backticks to straight '
    - normalize NBSP/figure/narrow NBSP to space
    - strip soft hyphen
    - collapse internal whitespace
    - keep colon logic outside this function
    """
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'").replace("´", "'")
    s = s.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
    s = s.replace("\u00ad", "")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def extract_header_and_body(full_text: str) -> Tuple[Dict[str, str], str]:
    """
    Extract header metadata and the normalized body from the saved .txt format.
    """
    header = {"message_id": "", "subject": "", "from": "", "to": "", "date": ""}
    lines = full_text.splitlines()

    # Header
    for line in lines:
        if line.startswith("message_id: "):
            header["message_id"] = line.split("message_id: ", 1)[1].strip()
        elif line.startswith("subject   : "):
            header["subject"] = line.split("subject   : ", 1)[1].strip()
        elif line.startswith("from      : "):
            header["from"] = line.split("from      : ", 1)[1].strip()
        elif line.startswith("to        : "):
            header["to"] = line.split("to        : ", 1)[1].strip()
        elif line.startswith("date      : "):
            header["date"] = line.split("date      : ", 1)[1].strip()
        if line.strip() == HDR_BODY_SEP:
            break

    # Body
    m = BODY_HEADER_RE.search(full_text)
    if m:
        body = full_text[m.end() :].strip()
    else:
        parts = full_text.split(HDR_BODY_SEP)
        if len(parts) >= 3:
            body = (HDR_BODY_SEP.join(parts[2:])).strip()
        else:
            body = full_text.strip()

    # Normalize body for consistent heading detection
    body_norm = normalize_for_compare(body)
    return header, body_norm


def find_heading_lines(body_norm: str) -> List[Tuple[int, str]]:
    """
    Return list of (line_index, heading_line_raw) for lines that end with a colon.
    Uses normalized body for detection.
    """
    lines = body_norm.splitlines()
    found = []
    for idx, ln in enumerate(lines):
        if HEADING_LINE_RE.match(ln):
            found.append((idx, ln.rstrip()))
    return found


def strip_trailing_colon(s: str) -> str:
    s = s.rstrip()
    return s[:-1].rstrip() if s.endswith(":") else s


def main():
    files = sorted(INPUT_DIR.glob("*.txt"))
    if not files:
        print(f"No .txt files in {INPUT_DIR.resolve()}")
        return

    unique_pos1 = {}
    unique_pos2 = {}
    unique_pos3 = {}
    # keep a small sample mapping for inspection
    per_file_first_three: List[Dict[str, str]] = []

    total = len(files)
    matched_any = 0

    for i, fp in enumerate(files, 1):
        text = fp.read_text(encoding="utf-8", errors="replace")
        header, body_norm = extract_header_and_body(text)
        headings = find_heading_lines(body_norm)  # list[(line_index, heading_line)]
        if headings:
            matched_any += 1

        # Collect first three headings (if present)
        first3 = headings[:3]
        pos1 = strip_trailing_colon(first3[0][1]) if len(first3) > 0 else ""
        pos2 = strip_trailing_colon(first3[1][1]) if len(first3) > 1 else ""
        pos3 = strip_trailing_colon(first3[2][1]) if len(first3) > 2 else ""

        # Track unique values with counts
        if pos1:
            unique_pos1[pos1] = unique_pos1.get(pos1, 0) + 1
        if pos2:
            unique_pos2[pos2] = unique_pos2.get(pos2, 0) + 1
        if pos3:
            unique_pos3[pos3] = unique_pos3.get(pos3, 0) + 1

        # Save a small mapping for manual review (optional)
        per_file_first_three.append(
            {
                "file": fp.name,
                "message_id": header.get("message_id", ""),
                "pos1": pos1,
                "pos2": pos2,
                "pos3": pos3,
            }
        )

        if i % 200 == 0 or i == total:
            print(f"Scanned {i}/{total} files...")

    print("\nSummary:")
    print(f"- Total files scanned: {total}")
    print(f"- Files with at least one heading ending with ':': {matched_any}")

    # Write unique sets to CSVs (value,count)
    def write_unique(path: Path, d: dict):
        rows = sorted(d.items(), key=lambda x: (-x[1], x[0].lower()))
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["heading_value", "count"])
            w.writerows(rows)
        print(f"Wrote {path.resolve()} ({len(rows)} unique values)")

    write_unique(OUT_UNIQUE_POS1, unique_pos1)
    write_unique(OUT_UNIQUE_POS2, unique_pos2)
    write_unique(OUT_UNIQUE_POS3, unique_pos3)

    # Optional: write a sample mapping file for inspection (file -> first three headings)
    with OUT_SAMPLE_MAP.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "message_id", "pos1", "pos2", "pos3"])
        w.writeheader()
        w.writerows(per_file_first_three[:1000])  # cap to 1000 rows to keep it light
    print(f"Wrote {OUT_SAMPLE_MAP.resolve()} (up to 1000 examples)")


if __name__ == "__main__":
    main()
