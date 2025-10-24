#!/usr/bin/env python3
import re
import json
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple, Optional

DEFAULT_INPUT_DIR = "1907"
OUT_JSON = "parsed_1907.json"

HDR_BODY_SEP = "=" * 67
BODY_HEADER_RE = re.compile(
    rf"^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*",
    re.MULTILINE,
)


def normalize_keep_newlines(s: str) -> str:
    """
    Normalize text while preserving newlines for slicing. Do NOT remove underscores here.
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
        .replace("\u00ad", "")
    )
    # Preserve newlines; collapse spaces/tabs
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def scrub_inline(s: str) -> str:
    """
    Scrub final field values only (after detection):
    - Remove markdown emphasis markers (* and _)
    - Replace literal backslash-n with a space
    - Collapse whitespace (including real newlines)
    """
    if s is None:
        return ""
    s = s.replace("*", "").replace("_", "")
    s = s.replace("\\n", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def clean_reading(val: str) -> str:
    """
    Normalize extracted reading strings:
    - remove any trailing punctuation/parenthesis
    - collapse spaces
    """
    if not val:
        return ""
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
    # Remove leading 'Subject:'
    m = re.match(r"^\s*Subject\s*:\s*(.*)$", subject_raw, flags=re.IGNORECASE)
    s = m.group(1) if m else subject_raw

    reading = None
    # Find any (...) that contains 'read' and extract the value after 'read'
    matches = list(re.finditer(r"\(([^)]*read[^)]*)\)", s, flags=re.IGNORECASE))
    if matches:
        pm = matches[-1]  # last '(read ...)'
        inside = pm.group(1)
        mread = re.search(
            r"\bread\b\s*\(?\s*(.+?)\s*\)?\s*$", inside, flags=re.IGNORECASE
        )
        if mread:
            reading = clean_reading(mread.group(1))
        # Remove exactly this parenthetical from subject
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


# Inline-friendly heading detectors
# Verse: "VERSE FOR <date>:" or "VERSE FOR TODAY:" (inline allowed)
VERSE_INLINE_RE = re.compile(
    r"""(?P<verse_hdr>\bVERSE\s+FOR\s+(?:\d{1,2}\s*[:/.\-]\s*\d{1,2}\s*[:/.\-]\s*(?:\d{2,4})|TODAY)\s*:)\s*(?P<after>.*)""",
    re.IGNORECASE,
)
# Reflection: "THOUGHT FOR TODAY:" (inline allowed)
THOUGHT_INLINE_RE = re.compile(
    r"""(?P<thought_hdr>\bTHOUGHT\s+FOR\s+TODAY\s*:)\s*(?P<after>.*)""",
    re.IGNORECASE,
)
# Prayer signature anywhere near the end
PRAYER_SIGNATURE_ANY_RE = re.compile(
    r"""\bPASTOR\s+AL\b""",
    re.IGNORECASE,
)

# Inline 'READ ...' detector near verse header; tolerate optional parentheses
# Matches: READ (Ps. 29), READ Ps. 27:1-8), (read Ps. 86:1-12)
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
      - reading: extracted from 'READ ...' near verse header (cleaned) or None
    """
    verse_pos = None
    thought_pos = None
    prayer_line = None
    reading = None

    for i, ln in enumerate(lines):
        if verse_pos is None:
            m = VERSE_INLINE_RE.search(ln)
            if m:
                verse_pos = (i, m.start("verse_hdr"))
                # try to capture reading on same or next line(s)
                tail = ln[m.end("verse_hdr") :]
                mread = READ_INLINE_RE.search(tail)
                if not mread and i + 1 < len(lines):
                    mread = READ_INLINE_RE.search(lines[i + 1])
                if mread:
                    reading = clean_reading(mread.group(1))
        if thought_pos is None:
            m2 = THOUGHT_INLINE_RE.search(ln)
            if m2:
                thought_pos = (i, m2.start("thought_hdr"))
        if prayer_line is None:
            if PRAYER_SIGNATURE_ANY_RE.search(ln):
                prayer_line = i

    return verse_pos, thought_pos, prayer_line, reading


def slice_sections(
    lines: List[str], verse_pos, thought_pos, prayer_line
) -> tuple[str, str, str]:
    """
    Slice verse/reflection/prayer based on inline heading positions.
    """
    verse_text = reflection_text = prayer_text = ""

    if verse_pos and thought_pos:
        v_line = verse_pos[0]
        t_line = thought_pos[0]
        v_after = VERSE_INLINE_RE.search(lines[v_line])
        if v_after:
            first_chunk = v_after.group("after").strip()
            chunks = [first_chunk] if first_chunk else []
            if t_line > v_line:
                between = lines[v_line + 1 : t_line]
                if between:
                    chunks.append("\n".join(between).strip())
            verse_text = "\n".join([c for c in chunks if c]).strip()

    if thought_pos:
        t_line = thought_pos[0]
        t_after = THOUGHT_INLINE_RE.search(lines[t_line])
        stop_line = prayer_line if prayer_line is not None else len(lines)
        chunks = []
        if t_after:
            first_chunk = t_after.group("after").strip()
            if first_chunk:
                chunks.append(first_chunk)
        if t_line + 1 < stop_line:
            chunks.append("\n".join(lines[t_line + 1 : stop_line]).strip())
        reflection_text = "\n".join([c for c in chunks if c]).strip()

    if prayer_line is not None:
        prayer_block = "\n".join(lines[prayer_line:]).strip()
        # remove leading "PASTOR AL" (tolerate underscores/quotes/extra spaces)
        prayer_block = re.sub(
            r'^\s*[*"_]*\s*PASTOR\s+AL\s*[*"_]*\s*[,:\-]?\s*',
            "",
            prayer_block,
            flags=re.IGNORECASE,
        )
        prayer_text = prayer_block.strip()

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

    # Subject + reading from subject (if present), subject cleaned (and parenthetical removed)
    subject_clean, reading_from_subject = parse_subject_and_reading(
        hdr.get("subject", "")
    )

    # Choose reading priority: subject first, then body 'READ ...'
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
        record["found_reading"] = False  # keep this last

    return record


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse 1907 devotionals (inline-friendly headings) into JSON"
    )
    ap.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Directory containing .txt messages (default: 1907)",
    )
    ap.add_argument(
        "--out", default=OUT_JSON, help="Output JSON file (default: parsed_1907.json)"
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
