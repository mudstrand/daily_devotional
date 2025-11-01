#!/usr/bin/env python3
"""
Daily Devotional Message Parser (batch 0903)

Parses “thoughts to live by” notes with structure:
-      Dateline banner: mm/dd/yy or mm/dd/yyyy, optional ~~~ FOOD FOR THOUGHT ~~~ title
      (tolerates 3–4 tildes and optional spacing; also allows date + title without phrase)
-      Verse header: Our/Bible Verse(s) for Today
-      Reflection header: Our/The Lesson for Today, or A Lesson to be learned
-      Prayer header: Prayer Suggestion or Suggested Prayer

Extracts:
-      header fields (message_id, subject, from, to, date)
-      verse, reflection, prayer
-      original_content (normalized)
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# =========================
# Batch configuration
# =========================


@dataclass
class BatchConfig:
    input_dir: str = "0903"
    out_json: str = "parsed_0903.json"
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
# Content slicing (headers)
# =========================

DATE_BANNER_RE = re.compile(
    r"""
    ^\s*
    (?:
        \d{2}/\d{2}/\d{2}(?:\d{2})?
    )
    (?:
        \s*~\s*~\s*~\s*(?:~\s*)?
        (?:
            (?:FOOD\s+FOR\s+THOUGHT|food\s+for\s+thought)
            \s*~\s*~\s*~\s*(?:~\s*)?.*
            |
            .+
        )
    )?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

VERSES_HDR_RE = re.compile(
    r"""
    ^\s*
    (?:
        (?:Our\s+)?Bible\s+Verse\s+for\s+Today
        |
        (?:Our\s+)?Bible\s+Verses\s+for\s+Today
    )
    \s*[:\-]?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

THOUGHTS_HDR_RE = re.compile(
    r"""
    ^\s*
    (?:
        Our\s+Lesson\s+for\s+Today
        |
        The\s+Lesson\s+for\s+Today
        |
        A\s+Lesson\s+to\s+be\s+learned
    )
    \s*[:\-]?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

PRAYER_HDR_RE = re.compile(
    r"^\s*(?:Prayer\s+Suggestion|Suggested\s+Prayer)\s*[:\-]?\s*$",
    re.IGNORECASE,
)

SIGNATURE_RE = re.compile(rf"^\s*{CFG.signature_name}\s*$", re.IGNORECASE)
TAIL_VERSE_RE = re.compile(
    r'^\s*The\s+Lord\s+said,?\s*".*?"\s*~?\s*-?\s*John[: ]\s*\d+:\d+\s*$', re.IGNORECASE
)


def slice_sections(body: str) -> Tuple[str, str, str]:
    lines = body.splitlines()

    # Skip an initial dateline/banner if present
    start = 0
    if lines and DATE_BANNER_RE.match(lines[0]):
        start = 1

    idx_verses = idx_thoughts = idx_prayer = idx_signature = None

    for i in range(start, len(lines)):
        ln = lines[i]
        if idx_verses is None and VERSES_HDR_RE.match(ln):
            idx_verses = i
            continue
        if idx_thoughts is None and THOUGHTS_HDR_RE.match(ln):
            idx_thoughts = i
            continue
        if idx_prayer is None and PRAYER_HDR_RE.match(ln):
            idx_prayer = i
            continue
        if idx_signature is None and (
            SIGNATURE_RE.match(ln) or TAIL_VERSE_RE.match(ln)
        ):
            idx_signature = i
            continue

    if idx_verses is None and idx_thoughts is None and idx_prayer is None:
        # Non-structured forward/admin note
        return "", "", ""

    def block(start_idx: Optional[int], stops: List[Optional[int]]) -> str:
        if start_idx is None:
            return ""
        after = [x for x in stops if x is not None and x > start_idx]
        stop = min(after) if after else len(lines)
        content = lines[start_idx + 1 : stop]
        # Trim trailing signature/tail lines
        while content and (
            SIGNATURE_RE.match(content[-1]) or TAIL_VERSE_RE.match(content[-1])
        ):
            content.pop()
        return "\n".join(content).strip()

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

    verse_raw, reflection_raw, prayer_raw = slice_sections(body)

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
        description="Parse devotionals (Verses → Lesson → Prayer)"
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
