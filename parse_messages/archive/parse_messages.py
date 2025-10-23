#!/usr/bin/env python3
import re
import csv
import json
import unicodedata
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# ------------- Configuration -------------
INPUT_DIR = Path("missing")  # folder with your saved Gmail .txt messages
OUTPUT_CSV = Path("parsed_todays_verses_thoughts_prayer.csv")
OUTPUT_JSON = Path("parsed_todays_verses_thoughts_prayer.json")

# Debug: print a normalized preview for the first N files that fail to match any tags (0 = off)
DEBUG_FIRST_N = 0

# Optional: case-insensitive tag matching (we also normalize apostrophes/spaces)
CASE_INSENSITIVE = True

# Exact tags for reporting (we match more flexibly than these raw strings)
VERSE_TAG_RAW = "Today’s Verses:"
REFLECTION_TAG_RAW = "Today’s Thoughts:"
PRAYER_TAG_RAW = "Today’s Prayer Suggestion:"
PRAYER_TERMINATOR = "Pastor Alvin and Marcie Sather"  # optional

# Header/body markers from your saved Gmail format
HDR_BODY_SEP = "=" * 67
BODY_HEADER_RE = re.compile(
    rf"^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*",
    re.MULTILINE,
)

# Apostrophe class for matching Today’s/Todays/Today`s/etc.
APO = r"[’'`´]"

# Regex patterns that accept apostrophe variants and optional spaces before colon
# Capture inline text after the colon for each tag.
VERSE_TAG_RE = re.compile(
    rf"^\s*Today{APO}?s\s+Verses\s*:\s*(?P<inline>.*)$", re.MULTILINE | re.IGNORECASE
)
REFLECTION_TAG_RE = re.compile(
    rf"^\s*Today{APO}?s\s+Thoughts\s*:\s*(?P<inline>.*)$", re.MULTILINE | re.IGNORECASE
)
PRAYER_TAG_RE = re.compile(
    rf"^\s*Today{APO}?s\s+Prayer\s+Suggestion\s*:\s*(?P<inline>.*)$",
    re.MULTILINE | re.IGNORECASE,
)

# ------------- Utilities -------------


def normalize_text_for_match(s: str) -> str:
    """
    Normalize text for robust matching:
    - Unicode NFKC
    - normalize apostrophes/backticks to straight '
    - normalize NBSP/figure space/narrow NBSP to regular space
    - strip soft hyphen
    Keep newlines intact.
    """
    if not s:
        return s
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'").replace("´", "'")
    s = s.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
    s = s.replace("\u00ad", "")
    return s


def extract_header_fields(full_text: str) -> Dict[str, str]:
    """
    From your saved Gmail .txt format, extract message_id, subject, from, to, date.
    Stops scanning once we hit the first separator to avoid reading the whole file.
    """
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
            # next lines likely contain the body header block
            break
    return hdr


def extract_body(full_text: str) -> str:
    """
    Extract text body after the “Body (clean, unformatted):” header block.
    Fallbacks: split by separators, or return entire text as last resort.
    """
    m = BODY_HEADER_RE.search(full_text)
    if m:
        return full_text[m.end() :].strip()
    # Fallback: try splitting by separators and taking the last significant chunk
    parts = full_text.split(HDR_BODY_SEP)
    if len(parts) >= 3:
        return (HDR_BODY_SEP.join(parts[2:])).strip()
    return full_text.strip()


def find_tag_positions(body: str) -> tuple[dict, list[str]]:
    """
    Find verse/reflection/prayer tag positions line-by-line on normalized text.
    Returns:
      ({'verse': (line_index, inline_text), 'reflection': (...), 'prayer': (...)} , normalized_lines)
    """
    norm = normalize_text_for_match(body)
    lines = norm.splitlines()

    found: dict = {}
    for idx, line in enumerate(lines):
        mv = VERSE_TAG_RE.match(line)
        if mv and "verse" not in found:
            found["verse"] = (idx, mv.group("inline").strip())
            continue
        mr = REFLECTION_TAG_RE.match(line)
        if mr and "reflection" not in found:
            found["reflection"] = (idx, mr.group("inline").strip())
            continue
        mp = PRAYER_TAG_RE.match(line)
        if mp and "prayer" not in found:
            found["prayer"] = (idx, mp.group("inline").strip())
            continue
    return found, lines


def find_terminator_index(lines: list[str], terminator: str) -> Optional[int]:
    """
    Find the line index where the prayer terminator occurs (after normalization), else None.
    """
    if not terminator:
        return None
    term_norm = normalize_text_for_match(terminator).strip().lower()
    for i, ln in enumerate(lines):
        if normalize_text_for_match(ln).strip().lower() == term_norm:
            return i
    return None


def slice_sections(body: str) -> tuple[str, str, str, dict]:
    """
    Return (verse, reflection, prayer, flags) using normalized matching and slicing.
    Each section includes inline content after the tag and continues to the earliest boundary:
      - next tag
      - (for prayer) optional terminator
      - end of body
    """
    tags, lines = find_tag_positions(body)

    flags = {
        "found_verse_tag": "verse" in tags,
        "found_reflection_tag": "reflection" in tags,
        "found_prayer_tag": "prayer" in tags,
        "found_prayer_terminator": False,
    }

    verse = reflection = prayer = ""

    if not tags:
        return verse, reflection, prayer, flags

    idx_map = {k: v[0] for k, v in tags.items()}

    term_idx = find_terminator_index(lines, PRAYER_TERMINATOR)
    if term_idx is not None:
        flags["found_prayer_terminator"] = True

    def slice_for(tag_key: str) -> str:
        if tag_key not in idx_map:
            return ""
        start_idx = idx_map[tag_key]
        stop_candidates = [v for k, v in idx_map.items() if k != tag_key]
        if tag_key == "prayer" and term_idx is not None:
            stop_candidates.append(term_idx)
        stop_idx = min(stop_candidates) if stop_candidates else len(lines)

        inline = tags[tag_key][1]
        parts: List[str] = []
        if inline:
            parts.append(inline)
        if start_idx + 1 < stop_idx:
            parts.append("\n".join(lines[start_idx + 1 : stop_idx]).strip())
        return "\n".join([p for p in parts if p]).strip()

    verse = slice_for("verse")
    reflection = slice_for("reflection")
    prayer = slice_for("prayer")

    return verse, reflection, prayer, flags


def parse_message_text(full_text: str) -> Dict[str, Optional[str]]:
    """
    Parse one saved Gmail text (your format) according to the specified tag strategy.
    """
    header = extract_header_fields(full_text)
    body = extract_body(full_text)

    verse, reflection, prayer, flags = slice_sections(body)

    return {
        "message_id": header.get("message_id", ""),
        "date_utc": header.get("date", ""),  # as saved; can normalize later if desired
        "subject": header.get("subject", ""),
        "verse": verse or None,
        "reflection": reflection or None,
        "prayer": prayer or None,
        "reading": None,  # optional; not defined in this strategy
        "original_content": body,
        **flags,
    }


# ------------- Runner -------------


def main():
    files = sorted(INPUT_DIR.glob("*.txt"))
    if not files:
        print(f"No .txt files found in {INPUT_DIR.resolve()}")
        return

    total = len(files)
    matched_all = 0
    matched_any = 0
    matched_verse = matched_reflection = matched_prayer = 0
    terminated_prayer = 0

    rows: List[Dict[str, Optional[str]]] = []

    for i, fp in enumerate(files, 1):
        text = fp.read_text(encoding="utf-8", errors="replace")
        rec = parse_message_text(text)

        v = rec["found_verse_tag"]
        r = rec["found_reflection_tag"]
        p = rec["found_prayer_tag"]
        if v:
            matched_verse += 1
        if r:
            matched_reflection += 1
        if p:
            matched_prayer += 1
        if v or r or p:
            matched_any += 1
        if v and r and p:
            matched_all += 1
        if rec["found_prayer_tag"] and rec["found_prayer_terminator"]:
            terminated_prayer += 1

        rows.append(
            {
                "message_id": rec["message_id"],
                "date_utc": rec["date_utc"],
                "subject": rec["subject"],
                "verse": rec["verse"] or "",
                "reflection": rec["reflection"] or "",
                "prayer": rec["prayer"] or "",
                "reading": rec["reading"] or "",
                "original_content": rec["original_content"] or "",
            }
        )

        if (not (v or r or p)) and DEBUG_FIRST_N and i <= DEBUG_FIRST_N:
            print(f"\n[DEBUG] No tags in {fp.name}")
            norm_preview = normalize_text_for_match(extract_body(text)).splitlines()[
                :20
            ]
            for ln in norm_preview:
                print("   ", ln)

        if i % 100 == 0 or i == total:
            print(f"Processed {i}/{total} files...")

    print("\nSummary (read-only):")
    print(f"- Total files scanned: {total}")
    print(f"- Files with any of the three tags: {matched_any}")
    print(f"- Files with all three tags: {matched_all}")
    print(f"- Files with verse tag: {matched_verse}")
    print(f"- Files with reflection tag: {matched_reflection}")
    print(f"- Files with prayer tag: {matched_prayer}")
    print(
        f"- Files where prayer terminated by '{PRAYER_TERMINATOR}': {terminated_prayer}"
    )

    # Write CSV and JSON outputs (read-only with respect to source messages)
    if rows:
        with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
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
        print(f"Wrote CSV: {OUTPUT_CSV.resolve()}")

        with OUTPUT_JSON.open("w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        print(f"Wrote JSON: {OUTPUT_JSON.resolve()}")


if __name__ == "__main__":
    main()
