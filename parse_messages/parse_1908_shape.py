#!/usr/bin/env python3
import re
import json
import unicodedata
from pathlib import Path
from typing import Dict, List

DEFAULT_INPUT_DIR = "1908"
OUT_JSON = "parsed_1908.json"

HDR_BODY_SEP = "=" * 67
BODY_HEADER_RE = re.compile(
    rf"^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*",
    re.MULTILINE,
)


def normalize_keep_newlines(s: str) -> str:
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
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def scrub_inline(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("*", "")
    s = s.replace("\\n", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_subject_and_reading(subject_raw: str) -> tuple[str, str | None]:
    """
    Strip leading 'Subject:' and extract '(read ...)' from the subject if present.
    Returns (clean_subject, reading or None).
    Examples:
      'THE LISTENING PRAYER  (read Ps. 86:1-12)' ->
        subject='THE LISTENING PRAYER', reading='Ps. 86:1-12'
      'SUNSHINE FOR YOUR SOUL  (read Ps. 84)' ->
        subject='SUNSHINE FOR YOUR SOUL', reading='Ps. 84'
    """
    if not subject_raw:
        return "", None

    # Remove leading 'Subject:' (case-insensitive)
    m = re.match(r"^\s*Subject\s*:\s*(.*)$", subject_raw, flags=re.IGNORECASE)
    s = m.group(1) if m else subject_raw

    # Try to find a '(read ...)' parenthetical
    # Capture text after 'read' within the last parenthetical that contains 'read'
    reading = None
    for pm in re.finditer(r"\(([^)]*read[^)]*)\)", s, flags=re.IGNORECASE):
        inside = pm.group(1)
        mread = re.search(r"read\s+(.+)$", inside, flags=re.IGNORECASE)
        if mread:
            reading = scrub_inline(mread.group(1))
            # Remove exactly this parenthetical from subject
            s = (s[: pm.start()] + s[pm.end() :]).strip()

    # Cleanup remaining whitespace and double spaces
    s = scrub_inline(s)
    return s, reading


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


# Headings for this month
VERSE_HEAD_RE = re.compile(
    r"""^\s*[*"']*\s*(verse\s+for\s+\d{1,2}\s*[:/.\-]\s*\d{1,2}\s*[:/.\-]\s*\d{2,4}|verse\s+for\s+today)\s*:\s*[*"']*\s*$""",
    re.IGNORECASE,
)
REFLECT_HEAD_RE = re.compile(
    r"""^\s*[*"']*\s*thought\s+for\s+today\s*:\s*[*"']*\s*$""",
    re.IGNORECASE,
)

# Prayer inference
PRAYER_SIGNATURE_RE = re.compile(
    r"""^\s*[*"']*\s*_?\s*pastor\s+al\s*_?\s*[*"']*\s*$""",
    re.IGNORECASE,
)
PRAYER_OPENER_RE = re.compile(
    r"""^\s*[*"']*\s*(dear\s+(?:heavenly\s+)?father|dear\s+lord|heavenly\s+father|lord\s+jesus)\b""",
    re.IGNORECASE,
)
PRAYER_AMEN_RE = re.compile(r"""\bamen\.?\s*$""", re.IGNORECASE)
PRAYER_LEADING_SIGNATURE_RE = re.compile(
    r"""^\s*[*"']*\s*_?\s*pastor\s+al\s*_?\s*[*"']*\s*[,:\-]?\s*""",
    re.IGNORECASE,
)


def parse_one(full_text: str) -> Dict[str, object]:
    hdr = extract_header_fields(full_text)
    body = normalize_keep_newlines(extract_body(full_text))
    lines = body.splitlines()

    v_idx = r_idx = None
    for i, ln in enumerate(lines):
        if v_idx is None and VERSE_HEAD_RE.match(ln):
            v_idx = i
            continue
        if r_idx is None and REFLECT_HEAD_RE.match(ln):
            r_idx = i
        if v_idx is not None and r_idx is not None:
            break

    # Prayer start
    p_idx = None
    if r_idx is not None:
        for i in range(r_idx + 1, len(lines)):
            if PRAYER_SIGNATURE_RE.match(lines[i]) or PRAYER_OPENER_RE.match(lines[i]):
                p_idx = i
                break
        if p_idx is None:
            for i in range(len(lines) - 1, r_idx, -1):
                if PRAYER_AMEN_RE.search(lines[i]):
                    j = i
                    while j > r_idx + 1 and lines[j - 1].strip():
                        j -= 1
                    p_idx = j
                    break

    # Slice raw sections
    verse_raw = reflection_raw = prayer_raw = ""
    if v_idx is not None and r_idx is not None:
        verse_raw = "\n".join(lines[v_idx + 1 : r_idx]).strip()
    if r_idx is not None:
        stop = p_idx if p_idx is not None else len(lines)
        reflection_raw = "\n".join(lines[r_idx + 1 : stop]).strip()
    if p_idx is not None:
        prayer_raw = "\n".join(lines[p_idx:]).strip()
        prayer_raw = PRAYER_LEADING_SIGNATURE_RE.sub("", prayer_raw, count=1)

    # Subject + reading from subject
    subject_clean, reading = parse_subject_and_reading(hdr.get("subject", ""))

    record: Dict[str, object] = {
        "message_id": hdr.get("message_id", ""),
        "date_utc": hdr.get("date", ""),
        "subject": subject_clean,
        "verse": scrub_inline(verse_raw),
        "reflection": scrub_inline(reflection_raw),
        "prayer": scrub_inline(prayer_raw),
        "original_content": body,
        "found_verse": v_idx is not None,
        "found_reflection": r_idx is not None,
        "found_prayer": p_idx is not None,
    }

    # Add reading if found, and set found_reading accordingly
    if reading:
        record["reading"] = reading
        record["found_reading"] = True
    else:
        record["found_reading"] = False  # ensure boolean at the bottom

    return record


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse 1908-shaped devotionals into JSON with subject-reading extraction"
    )
    ap.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Directory containing .txt messages (default: 1908)",
    )
    ap.add_argument(
        "--out", default=OUT_JSON, help="Output JSON file (default: parsed_1908.json)"
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
