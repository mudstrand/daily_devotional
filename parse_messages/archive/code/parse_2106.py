#!/usr/bin/env python3
import re
import json
import unicodedata
from pathlib import Path
from typing import Dict, List

DEFAULT_INPUT_DIR = "2106"
OUT_JSON = "parsed_2106.json"

HDR_BODY_SEP = "=" * 67
BODY_HEADER_RE = re.compile(
    rf"^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*",
    re.MULTILINE,
)

# Repairs words that were hyphenated across line breaks:
#   "for-\n\ngiveness" -> "forgiveness"
#   "ex-\n ample"      -> "example"
# Keeps true hyphens inside lines (e.g., "re-form") intact.
HYPHEN_LINEBREAK_RE = re.compile(r"-\s*(?:\r?\n)+\s*")


def repair_linebreak_hyphenation(s: str) -> str:
    if not s:
        return ""
    # Only remove hyphens that are immediately followed by linebreak(s),
    # targeting soft hyphenation due to wrapping.
    return HYPHEN_LINEBREAK_RE.sub("", s)


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
        .replace("\u00ad", "")  # soft hyphen
    )

    # Rejoin words split across line breaks via hyphenation
    s = repair_linebreak_hyphenation(s)

    # Collapse spaces/tabs but keep newlines for section parsing
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def scrub_inline(s: str) -> str:
    if s is None:
        return ""
    # Remove common markdown/emphasis markers (extend if needed)
    s = s.replace("*", "")
    # Normalize escaped newlines and actual newlines to spaces
    s = s.replace("\\n", " ")
    s = re.sub(r"(?:\r?\n)+", " ", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def scrub_subject(s: str) -> str:
    if not s:
        return ""
    m = re.match(r"^\s*Subject\s*:\s*(.*)$", s, flags=re.IGNORECASE)
    if m:
        s = m.group(1)
    return scrub_inline(s)


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


VERSE_HEAD_RE = re.compile(
    r"""^\s*[*"']*\s*(my\s+verse|my\s+verses)\s*:\s*[*"']*\s*$""", re.IGNORECASE
)
REFLECT_HEAD_RE = re.compile(
    r"""^\s*[*"']*\s*(today'?s\s+reflection)\s*:\s*[*"']*\s*$""", re.IGNORECASE
)

PRAYER_SIGNATURE_RE = re.compile(
    r"""^\s*[*"']*\s*pastor\s+sather\s*[*"']*\s*$""", re.IGNORECASE
)
PRAYER_OPENER_RE = re.compile(
    r"""^\s*[*"']*\s*(dear\s+(?:heavenly\s+)?father|dear\s+lord|heavenly\s+father|lord\s+jesus)\b""",
    re.IGNORECASE,
)
PRAYER_AMEN_RE = re.compile(r"""\bamen\.?\s*$""", re.IGNORECASE)
PRAYER_LEADING_SIGNATURE_RE = re.compile(
    r"""^\s*[*"']*\s*pastor\s+sather\s*[*"']*\s*[,:\-]?\s*""", re.IGNORECASE
)


def parse_one(full_text: str) -> Dict[str, object]:
    hdr = extract_header_fields(full_text)
    body = normalize_keep_newlines(extract_body(full_text))

    # Optional: flattened, fully scrubbed body (handy for search/display)
    body_flat = scrub_inline(body)

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

    p_idx = None
    if r_idx is not None:
        # Prayer usually follows reflection; find the opening
        for i in range(r_idx + 1, len(lines)):
            if PRAYER_SIGNATURE_RE.match(lines[i]) or PRAYER_OPENER_RE.match(lines[i]):
                p_idx = i
                break
        # Fallback: find trailing Amen block
        if p_idx is None:
            for i in range(len(lines) - 1, r_idx, -1):
                if PRAYER_AMEN_RE.search(lines[i]):
                    j = i
                    while j > r_idx + 1 and lines[j - 1].strip():
                        j -= 1
                    p_idx = j
                    break

    verse_raw = reflection_raw = prayer_raw = ""
    if v_idx is not None and r_idx is not None:
        verse_raw = "\n".join(lines[v_idx + 1 : r_idx]).strip()
    if r_idx is not None:
        stop = p_idx if p_idx is not None else len(lines)
        reflection_raw = "\n".join(lines[r_idx + 1 : stop]).strip()
    if p_idx is not None:
        prayer_raw = "\n".join(lines[p_idx:]).strip()

    if prayer_raw:
        prayer_raw = PRAYER_LEADING_SIGNATURE_RE.sub("", prayer_raw, count=1)

    record: Dict[str, object] = {
        "message_id": hdr.get("message_id", ""),
        "date_utc": hdr.get("date", ""),
        "subject": scrub_subject(hdr.get("subject", "")),
        "verse": scrub_inline(verse_raw),
        "reflection": scrub_inline(reflection_raw),
        "prayer": scrub_inline(prayer_raw),
        "original_content": body,
        "original_content_flat": body_flat,
        "found_verse": v_idx is not None,
        "found_reflection": r_idx is not None,
        "found_prayer": p_idx is not None,
        "found_reading": False,  # always present and at the bottom
    }
    return record


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse 2106-shaped devotionals into JSON with scrubbing (found_reading=false at bottom)"
    )
    ap.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Directory containing .txt messages (default: 2106)",
    )
    ap.add_argument(
        "--out", default=OUT_JSON, help="Output JSON file (default: parsed_2106.json)"
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
