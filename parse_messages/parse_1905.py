#!/usr/bin/env python3
import re
import json
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple, Optional

DEFAULT_INPUT_DIR = "1905"
OUT_JSON = "parsed_1905.json"

HDR_BODY_SEP = "=" * 67
BODY_HEADER_RE = re.compile(
    rf"^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*",
    re.MULTILINE,
)

# Repairs words that were hyphenated across line breaks:
#   "re-\njoin" -> "rejoin"
HYPHEN_LINEBREAK_RE = re.compile(r"-\s*(?:\r?\n)+\s*")


def repair_linebreak_hyphenation(s: str) -> str:
    if not s:
        return ""
    return HYPHEN_LINEBREAK_RE.sub("", s)


def normalize_keep_newlines(s: str) -> str:
    """
    Normalize text while preserving newlines for slicing. Do NOT remove underscores here.
    Also: repair hyphenations at line breaks before detection.
    """
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = (
        s.replace("’", "'")
        .replace("‘", "'")
        .replace("`", "'")
        .replace("´", "'")
        .replace("\u00a0", " ")
        .replace("\u2007", " ")
        .replace("\u202f", " ")
        .replace("\u00ad", "")  # soft hyphen
    )
    # Rejoin words split across line breaks by hyphen
    s = repair_linebreak_hyphenation(s)
    # Preserve newlines; collapse only spaces/tabs
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def scrub_inline(s: str) -> str:
    """
    Scrub final field values only (after detection & slicing):
    - remove markdown emphasis markers (* and _)
    - replace literal \n with a space
    - collapse whitespace including real newlines
    """
    if s is None:
        return ""
    s = s.replace("*", "").replace("_", "")
    s = s.replace("\\n", " ")
    s = re.sub(r"(?:\r?\n)+", " ", s)
    s = re.sub(r"\s+", " ", s)
    # Clean doubled punctuation artifacts like ".."
    s = re.sub(r"\.{2,}", ".", s)
    s = re.sub(r"\s*([,.;:])\s*", r"\1 ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def clean_reading(val: str) -> str:
    """
    Normalize extracted reading strings:
    - remove embedded real newlines
    - remove trailing punctuation/parenthesis
    - collapse spaces
    """
    if not val:
        return ""
    val = val.replace("\n", " ")
    val = re.sub(r"[\)\.;,\s]+$", "", val)
    val = re.sub(r"\s+", " ", val).strip()
    return val


def parse_subject_and_reading(subject_raw: str) -> tuple[str, Optional[str]]:
    """
    Strip leading 'Subject:' and extract '(read ...)' from the subject if present.
    Returns (clean_subject, reading or None).
    """
    if not subject_raw:
        return "", None
    m = re.match(r"^\s*Subject\s*:\s*(.*)$", subject_raw, flags=re.IGNORECASE)
    s = m.group(1) if m else subject_raw

    reading = None
    matches = list(re.finditer(r"\(([^)]*read[^)]*)\)", s, flags=re.IGNORECASE))
    if matches:
        pm = matches[-1]
        inside = pm.group(1)
        mread = re.search(
            r"\bread\b\s*\(?\s*(.+?)\s*\)?\s*$", inside, flags=re.IGNORECASE
        )
        if mread:
            reading = clean_reading(mread.group(1))
        s = (s[: pm.start()] + s[pm.end() :]).strip()

    s = scrub_inline(s)
    return s, (reading or None)


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


# Date variants used in verse header:
# - Month name + day (e.g., MAY 29)
# - M/D, M/D/YY, M/D/YYYY
# - M-D, M-D-YY, M-D-YYYY
DATE_VARIANT = r"(?:[A-Z][a-z]+\s+\d{1,2}|\d{1,2}\s*[:/.\-]\s*\d{1,2}(?:\s*[:/.\-]\s*(?:\d{2}|\d{4}))?)"

# Verse header may appear alone on the line, with colon optional spacing after
VERSE_LINE_RE = re.compile(
    rf"""^\s*(?P<hdr>VERSE\s+FOR\s+(?:{DATE_VARIANT}|TODAY))\s*:\s*(?P<after>.*)$""",
    re.IGNORECASE,
)

# Also retain the previous inline form (verse + content on same line)
VERSE_INLINE_RE = re.compile(
    rf"""(?P<verse_hdr>\bVERSE\s+FOR\s+(?:{DATE_VARIANT}|TODAY)\s*:)\s*(?P<after>.*)""",
    re.IGNORECASE,
)

# Thought header can be "THOUGHT FOR TODAY:" or "THOUGHT FOR TODAY" on its own line
THOUGHT_LINE_RE = re.compile(
    r"""^\s*THOUGHT\s+FOR\s+TODAY\s*:?\s*$""",
    re.IGNORECASE,
)

# When it's inline (same line content after colon), keep the original joiner too
THOUGHT_JOIN_RE = re.compile(
    r"""\bTHOUGHT\s+FOR\s+TODAY\s*:\s*""",
    re.IGNORECASE,
)

PRAYER_SIGNATURE_ANY_RE = re.compile(
    r"""\bPASTOR\s+AL\b""",
    re.IGNORECASE,
)

PAREN_DOTALL_RE = re.compile(r"\((.*?)\)", re.DOTALL)

READ_INLINE_RE = re.compile(
    r"""\bread\b\s*\(?\s*([A-Za-z0-9\.\:\-\;\s,]+?)\s*\)?\b""",
    re.IGNORECASE,
)


def find_positions_and_reading(
    lines: List[str],
) -> tuple[
    Optional[Tuple[int, int]], Optional[Tuple[int, int]], Optional[int], Optional[str]
]:
    """
    Return:
      - verse_pos: (line_index, column) where verse header occurs
      - thought_pos: (line_index, column) where thought header occurs
      - prayer_line: line index where 'PASTOR AL' appears (if any)
      - reading: extracted near verse header (cleaned) or None
    """
    verse_pos = None
    thought_pos = None
    prayer_line = None
    reading = None

    for i, ln in enumerate(lines):
        # Strong verse header matching whether inline or line form
        if verse_pos is None:
            m_inline = VERSE_INLINE_RE.search(ln)
            m_line = VERSE_LINE_RE.match(ln)
            if m_inline:
                verse_pos = (i, m_inline.start("verse_hdr"))
                # try to pull reading from parentheses or READ(...) within a 2-line window
                window = ln
                if i + 1 < len(lines):
                    window += "\n" + lines[i + 1]
                parens = list(PAREN_DOTALL_RE.finditer(window))
                if len(parens) >= 2:
                    reading = clean_reading(parens[1].group(1))
                else:
                    tail = ln[m_inline.end("verse_hdr") :]
                    mread = READ_INLINE_RE.search(tail)
                    if not mread and i + 1 < len(lines):
                        mread = READ_INLINE_RE.search(lines[i + 1])
                    if mread:
                        reading = clean_reading(mread.group(1))
            elif m_line:
                verse_pos = (i, m_line.start("hdr"))
                # attempt reading similarly from the line + next
                window = ln
                if i + 1 < len(lines):
                    window += "\n" + lines[i + 1]
                parens = list(PAREN_DOTALL_RE.finditer(window))
                if len(parens) >= 2:
                    reading = clean_reading(parens[1].group(1))
                else:
                    tail = m_line.group("after")
                    mread = READ_INLINE_RE.search(tail) if tail else None
                    if not mread and i + 1 < len(lines):
                        mread = READ_INLINE_RE.search(lines[i + 1])
                    if mread:
                        reading = clean_reading(mread.group(1))

        # Thought header can be inline or on its own line
        if thought_pos is None:
            if THOUGHT_LINE_RE.match(ln):
                thought_pos = (i, 0)
            else:
                # inline on same line
                m2 = THOUGHT_JOIN_RE.search(ln)
                if m2:
                    thought_pos = (i, m2.start())

        # Prayer signature anywhere
        if prayer_line is None and PRAYER_SIGNATURE_ANY_RE.search(ln):
            prayer_line = i

    return verse_pos, thought_pos, prayer_line, reading


def slice_sections(
    lines: List[str], verse_pos, thought_pos, prayer_line
) -> tuple[str, str, str]:
    """
    Slice verse/reflection/prayer based on header positions.
    Supports:
      - Verse header on its own line with following lines holding the verse
      - Thought header on its own line (content starts next line)
      - Thought header inline (content after colon)
    """
    verse_text = reflection_text = prayer_text = ""

    # Verse slice
    if verse_pos:
        v_line = verse_pos[0]

        # If the verse header is inline with content, capture that tail
        m_inline = VERSE_INLINE_RE.search(lines[v_line])
        m_line = VERSE_LINE_RE.match(lines[v_line])

        chunks = []
        if m_inline:
            first_chunk = m_inline.group("after").strip()
            if first_chunk:
                chunks.append(first_chunk)
        elif m_line:
            # after-part on same line (rare in this corpus), then subsequent lines until thought header
            after = m_line.group("after").strip()
            if after:
                chunks.append(after)

        # Add subsequent lines up to the thought header (if present)
        t_line = thought_pos[0] if thought_pos else len(lines)
        if v_line + 1 < t_line:
            between = lines[v_line + 1 : t_line]
            if between:
                chunks.append("\n".join(between).strip())
        verse_text = "\n".join([c for c in chunks if c]).strip()

    # Thought slice
    if thought_pos:
        t_line = thought_pos[0]

        # Inline content after colon on the same line
        inline_after = ""
        m_inline = THOUGHT_JOIN_RE.search(lines[t_line])
        if m_inline:
            inline_after = lines[t_line][m_inline.end() :].strip()

        chunks = []
        if inline_after:
            chunks.append(inline_after)

        # Content from the next line onward until prayer or end
        start_idx = t_line + 1
        stop_line = prayer_line if prayer_line is not None else len(lines)
        if start_idx < stop_line:
            chunks.append("\n".join(lines[start_idx:stop_line]).strip())
        reflection_text = "\n".join([c for c in chunks if c]).strip()

        # Strip trailing "PASTOR AL" if it ended up included
        reflection_text = re.sub(
            r'\s*[*"_]*\s*PASTOR\s+AL\s*[*"_]*\s*[,:\-]?\s*$',
            "",
            reflection_text,
            flags=re.IGNORECASE,
        ).strip()

    # Prayer slice (signature line and after; typically just the signature)
    if prayer_line is not None:
        prayer_block = "\n".join(lines[prayer_line:]).strip()
        # remove leading "PASTOR AL"
        prayer_block = re.sub(
            r'^\s*[*"_]*\s*PASTOR\s+AL\s*[*"_]*\s*[,:\-]?\s*',
            "",
            prayer_block,
            flags=re.IGNORECASE,
        )
        prayer_text = prayer_block.strip()
    else:
        prayer_text = ""

    return verse_text, reflection_text, prayer_text


def parse_one(full_text: str) -> Dict[str, object]:
    hdr = extract_header_fields(full_text)
    body = normalize_keep_newlines(extract_body(full_text))
    lines = body.splitlines()

    verse_pos, thought_pos, prayer_line, reading_from_body = find_positions_and_reading(
        lines
    )
    verse_raw, reflection_raw, prayer_raw = slice_sections(
        lines, verse_pos, thought_pos, prayer_line
    )

    subject_clean, reading_from_subject = parse_subject_and_reading(
        hdr.get("subject", "")
    )

    reading_val = reading_from_subject or reading_from_body

    record: Dict[str, object] = {
        "message_id": hdr.get("message_id", ""),
        "date_utc": hdr.get("date", ""),
        "subject": subject_clean,
        "verse": scrub_inline(verse_raw),
        "reflection": scrub_inline(reflection_raw),
        "prayer": scrub_inline(prayer_raw),
        "original_content": body,
        "found_verse": bool(verse_raw),
        "found_reflection": bool(reflection_raw),
        "found_prayer": bool(prayer_raw),
    }

    if reading_val:
        record["reading"] = reading_val
        record["found_reading"] = True
    else:
        record["found_reading"] = False  # keep at bottom

    return record


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse 1905 devotionals (robust VERSE/THOUGHT headers, hyphenation repair)"
    )
    ap.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Directory containing .txt messages (default: 1905)",
    )
    ap.add_argument(
        "--out", default=OUT_JSON, help="Output JSON file (default: parsed_1905.json)"
    )
    args = ap.parse_args()

    src = Path(args.input_dir)
    files = sorted(src.glob("*.txt"))
    if not files:
        print(f"No files found in {src.resolve()}")
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
