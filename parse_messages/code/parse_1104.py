#!/usr/bin/env python3
"""
Daily Devotional Message Parser (batch 1305)

Parses:
-  Verse header: "Verse for Today:", "Today's Verse:", "Today's Scripture:"
-  Reflection header: "Food for Thought:", "Today's Thoughts/Thought/Lesson", "Thoughts to live by:"
-  Prayer header: "Today's Prayer:", "Today's Prayer Suggestion:"

Extracts:
-  header fields (message_id, subject, from, to, date)
-  verse (includes multi-line reference and scripture)
-  reflection
-  prayer
-  original_content (normalized)
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


# =========================
# Batch configuration
# =========================


@dataclass
class BatchConfig:
    input_dir: str = "1104"
    out_json: str = "parsed_1104.json"
    header_body_sep: str = "=" * 67
    signature_name: str = r"(?:Pastor\s+Al(?:vin)?\s*(?:&|and)\s*Marcie\s+Sather)"


CFG = BatchConfig()


# =========================
# Normalization helpers
# =========================

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
    s = s.replace("\\n", " ")
    s = s.replace("_", "")
    s = re.sub(r"(?:\r?\n)+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # punctuation spacing and verse refs
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    s = re.sub(r"([,.;])\s*", r"\1 ", s)
    s = re.sub(r"(\b\d+):\s+(\d+\b)", r"\1:\2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# =========================
# Header/body extraction
# =========================

BODY_HEADER_RE = re.compile(
    rf"^{re.escape(CFG.header_body_sep)}\s*Body \(clean, unformatted\):\s*{re.escape(CFG.header_body_sep)}\s*",
    re.MULTILINE,
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


# =========================
# Content slicing (Today’s sections)
# =========================

# Verse headers (Verse for Today / Today’s Verse / Today’s Scripture)
VERSES_HDR_RE = re.compile(
    r"^\s*(?:Verse\s+for\s+Today|Today'?s\s+(?:Verse|Scripture))\s*[:\-]\s*$",
    re.IGNORECASE,
)

# Reflection headers: Food for Thought / Today's Thoughts/Thought/Lesson / Thoughts to live by
THOUGHTS_HDR_RE = re.compile(
    r"^\s*(?:Food\s+for\s+Thought|Today'?s\s+(?:Thoughts?|Lesson)|Thoughts?\s+to\s+live\s+by)\s*[:\-]\s*$",
    re.IGNORECASE,
)

# Prayer headers: Today's Prayer / Today's Prayer Suggestion
PRAYER_HDR_RE = re.compile(
    r"^\s*Today'?s\s+Prayer(?:\s+Suggestion)?\s*[:\-]\s*$",
    re.IGNORECASE,
)

# Short forms (robustness)
ALT_THOUGHT_SHORT_RE = re.compile(r"^\s*THOUGHT(?:S)?\s*[:\-]\s*$", re.IGNORECASE)
ALT_PRAYER_SHORT_RE = re.compile(r"^\s*PRAYER\s*[:\-]\s*$", re.IGNORECASE)

# Signature marker
SIGNATURE_RE = re.compile(rf"^\s*{CFG.signature_name}\s*$", re.IGNORECASE)

# Filter out trailing admin notes in captured section blocks (travel/move notices)
TAIL_NOTE_RE = re.compile(
    r"^\s*(I will be|We (are|were)|Have a blessed|Have a Blessed|I will be away|We have|We've)\b",
    re.IGNORECASE,
)


def slice_todays_sections(body: str) -> tuple[str, str, str]:
    lines = body.splitlines()
    idx_verses = idx_thoughts = idx_prayer = idx_signature = None

    for i, ln in enumerate(lines):
        if idx_verses is None and VERSES_HDR_RE.match(ln):
            idx_verses = i
        if idx_thoughts is None and (
            THOUGHTS_HDR_RE.match(ln) or ALT_THOUGHT_SHORT_RE.match(ln)
        ):
            idx_thoughts = i
        if idx_prayer is None and (
            PRAYER_HDR_RE.match(ln) or ALT_PRAYER_SHORT_RE.match(ln)
        ):
            idx_prayer = i
        if idx_signature is None and SIGNATURE_RE.match(ln):
            idx_signature = i

    # If no recognized headers, return empties (these items are more freeform)
    if idx_verses is None and idx_thoughts is None and idx_prayer is None:
        return "", "", ""

    def block(start_idx: Optional[int], stops: List[Optional[int]]) -> str:
        if start_idx is None:
            return ""
        after = [x for x in stops if x is not None and x > start_idx]
        stop = (
            min(after)
            if after
            else (
                idx_signature
                if idx_signature and idx_signature > start_idx
                else len(lines)
            )
        )
        chunk = "\n".join(lines[start_idx + 1 : stop]).strip()
        # Filter obvious trailing admin notes within the chunk while preserving devotional content
        filtered = []
        for cl in chunk.splitlines():
            if cl.strip() and not TAIL_NOTE_RE.match(cl):
                filtered.append(cl)
        return "\n".join(filtered).strip()

    verse_raw = block(idx_verses, [idx_thoughts, idx_prayer, idx_signature])
    reflection_raw = block(idx_thoughts, [idx_prayer, idx_signature])
    prayer_raw = block(idx_prayer, [idx_signature])

    return verse_raw, reflection_raw, prayer_raw


# =========================
# Record assembly
# =========================


def parse_one(full_text: str) -> Dict[str, object]:
    hdr = extract_header_fields(full_text)
    raw_body = extract_body(full_text)
    body = normalize_keep_newlines(raw_body)

    verse_raw, reflection_raw, prayer_raw = slice_todays_sections(body)

    rec: Dict[str, object] = {
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
    return rec


# =========================
# CLI
# =========================


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse 1305 devotionals (Verse/Thoughts/Lesson → Prayer)"
    )
    ap.add_argument(
        "--input-dir",
        default=CFG.input_dir,
        help="Directory containing .txt messages (default: 1305)",
    )
    ap.add_argument(
        "--out",
        default=CFG.out_json,
        help="Output JSON file (default: parsed_1305.json)",
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
