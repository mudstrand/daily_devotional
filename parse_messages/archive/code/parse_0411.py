#!/usr/bin/env python3
"""
Daily Devotional Message Parser (Meditation/Devotion → Thought → Prayer) — batch 0612

Parses “thoughts to live by” notes with structure:
-               Optional dateline banner: mm/dd/yy or mm/dd/yyyy (tolerates stray spaces and 11//19/08),
               optional ~~~ (food for thought) ~~~ title (case-insensitive)
-               Verse section header: Our Meditation for <x>:  OR Our Devotion for Today:
-               Reflection section header: Our Thought(s) for Today:
-               Prayer section header: Our Prayer for Today:

Extracts:
-               header fields (message_id, subject, from, to, date)
-               verse, reflection, prayer
-               original_content (normalized)
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class BatchConfig:
    input_dir: str = "0411"
    out_json: str = "parsed_0411.json"
    header_body_sep: str = "=" * 67
    signature_name: str = r"(?:Pastor\s+Al(?:vin)?\s*(?:&|and)\s*Marcie\s+Sather)"


CFG = BatchConfig()

HYPHEN_LINEBREAK_RE = re.compile(r"-\s*(?:\r?\n)+\s*")


def repair_linebreak_hyphenation(s: str) -> str:
    if not s:
        return ""
    return HYPHEN_LINEBREAK_RE.sub("", s)


def normalize_keep_newlines(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = (
        s.replace("’", "'")
        .replace("‘", "'")
        .replace("\u00a0", " ")
        .replace("\u2007", " ")
        .replace("\u202f", " ")
        .replace("\u00ad", "")
    )
    s = repair_linebreak_hyphenation(s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def scrub_inline(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\\n", " ").replace("_", "")
    s = re.sub(r"(?:\r?\n)+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    s = re.sub(r"([,.;])\s*", r"\1 ", s)
    s = re.sub(r"(\b\d+):\s+(\d+\b)", r"\1:\2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


BODY_HEADER_RE = re.compile(
    rf"^{re.escape(CFG.header_body_sep)}\s*Body \(clean, unformatted\):\s*{re.escape(CFG.header_body_sep)}\s*",
    re.MULTILINE,
)

# Optional dateline banner (tolerates 11//19/08 and spaces in date)
DATE_BANNER_RE = re.compile(
    r"""
    ^\s*
    (?:
        \d{2}//\d{2}/\d{2}
        |
        \d{2}/\s*\d{2}/\d{2}(?:\d{2})?
    )
    (?:
        \s*~\s*~\s*~\s*(?:~\s*)?
        \s*\(?\s*food\s+for\s+thought\s*\)?\s*
        \s*~\s*~\s*~\s*(?:~\s*)?.*
        |
        \s*~\s*~\s*~\s*(?:~\s*)?.*
    )?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Headers (explicit, with minor flexibility for 0612 variants):

# Verse section begins with: Our Meditation for <x>:   OR Our Devotion for Today:
MEDITATION_OR_DEVOTION_HDR_RE = re.compile(
    r"""
    ^\s*
    (?:
        Our\s+Meditation\s+for\b.*?    # Our Meditation for <...>:
        |
        Our\s+Devotion\s+for\s+Today    # Our Devotion for Today:
    )
    \s*:\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Reflection section begins with: Our Thought for Today: (sometimes “Our Thoughts for Today:”)
THOUGHT_HDR_RE = re.compile(
    r"""
    ^\s*
    Our\s+Thoughts?\s+for\s+Today
    \s*:\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Prayer section begins with: Our Prayer for Today:
PRAYER_HDR_RE = re.compile(
    r"""
    ^\s*
    Our\s+Prayer\s+for\s+Today
    \s*:\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Sign-off and tail verse trimmer
SIGNATURE_RE = re.compile(rf"^\s*{CFG.signature_name}\s*$", re.IGNORECASE)
TAIL_VERSE_RE = re.compile(
    r'^\s*The\s+Lord\s+said,?\s*".*?"\s*~?\s*-?\s*John[: ]\s*\d+:\d+\s*$',
    re.IGNORECASE,
)


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
        if line.strip() == CFG.header_body_sep:
            break
    return hdr


def extract_body(full_text: str) -> str:
    m = BODY_HEADER_RE.search(full_text)
    if m:
        return full_text[m.end() :].strip()
    parts = full_text.split(CFG.header_body_sep)
    if len(parts) >= 3:
        return (CFG.header_body_sep.join(parts[2:])).strip()
    return full_text.strip()


def slice_sections(body: str) -> Tuple[str, str, str]:
    lines = body.splitlines()
    start = 0
    if lines and DATE_BANNER_RE.match(lines[0]):
        start = 1

    idx_verse: Optional[int] = None
    idx_thought: Optional[int] = None
    idx_prayer: Optional[int] = None
    idx_signature: Optional[int] = None

    for i in range(start, len(lines)):
        ln = lines[i]
        if idx_verse is None and MEDITATION_OR_DEVOTION_HDR_RE.match(ln):
            idx_verse = i
            continue
        if idx_thought is None and THOUGHT_HDR_RE.match(ln):
            idx_thought = i
            continue
        if idx_prayer is None and PRAYER_HDR_RE.match(ln):
            idx_prayer = i
            continue
        if idx_signature is None and (
            SIGNATURE_RE.match(ln) or TAIL_VERSE_RE.match(ln)
        ):
            idx_signature = i
            continue

    if idx_verse is None and idx_thought is None and idx_prayer is None:
        return "", "", ""

    def block(start_idx: Optional[int], stops: List[Optional[int]]) -> str:
        if start_idx is None:
            return ""
        after = [x for x in stops if x is not None and x > start_idx]
        stop = min(after) if after else len(lines)
        content = lines[start_idx + 1 : stop]
        while content and (
            SIGNATURE_RE.match(content[-1]) or TAIL_VERSE_RE.match(content[-1])
        ):
            content.pop()
        return "\n".join(content).strip()

    verse_raw = block(idx_verse, [idx_thought, idx_prayer, idx_signature])
    reflection_raw = block(idx_thought, [idx_prayer, idx_signature])
    prayer_raw = block(idx_prayer, [idx_signature])
    return verse_raw, reflection_raw, prayer_raw


def parse_one(full_text: str) -> Dict[str, object]:
    hdr = extract_header_fields(full_text)
    raw_body = extract_body(full_text)
    body = normalize_keep_newlines(raw_body)
    verse_raw, reflection_raw, prayer_raw = slice_sections(body)
    return {
        "message_id": hdr.get("message_id", ""),
        "date_utc": hdr.get("date", ""),
        "subject": scrub_inline(hdr.get("subject", "")),
        "verse": scrub_inline(verse_raw),
        "reflection": scrub_inline(reflection_raw),
        "prayer": scrub_inline(prayer_raw),
        "reading": "",
        "original_content": body,
        "found_verse": bool(verse_raw),
        "found_reflection": bool(reflection_raw),
        "found_prayer": bool(prayer_raw),
        "found_reading": False,
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse devotionals (Meditation/Devotion → Thought → Prayer)"
    )
    ap.add_argument(
        "--input-dir",
        default=CFG.input_dir,
        help=f"Directory containing .txt messages (default: {CFG.input_dir})",
    )
    ap.add_argument(
        "--out",
        default=CFG.out_json,
        help=f"Output JSON file (default: {CFG.out_json})",
    )
    args = ap.parse_args()

    input_dir = Path(args.input_dir)
    files = sorted(input_dir.glob("*.txt"))
    if not files:
        print(f"No files found in {input_dir.resolve()}")
        Path(args.out).write_text("[]", encoding="utf-8")
        return

    rows: List[Dict[str, object]] = []
    for fp in files:
        txt = fp.read_text(encoding="utf-8", errors="replace")
        rows.append(parse_one(txt))

    Path(args.out).write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {len(rows)} records to {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()
