#!/usr/bin/env python3
import re
import json
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple, Optional

DEFAULT_INPUT_DIR = '1902'
OUT_JSON = 'parsed_1902.json'

HDR_BODY_SEP = '=' * 67
BODY_HEADER_RE = re.compile(
    rf'^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*',
    re.MULTILINE,
)

# Repairs words that were hyphenated across line breaks:
#   "re-\njoin" -> "rejoin"
HYPHEN_LINEBREAK_RE = re.compile(r'-\s*(?:\r?\n)+\s*')


def repair_linebreak_hyphenation(s: str) -> str:
    if not s:
        return ''
    return HYPHEN_LINEBREAK_RE.sub('', s)


def normalize_keep_newlines(s: str) -> str:
    """
    Normalize text while preserving newlines for slicing. Do NOT remove underscores here.
    Also: repair hyphenations at line breaks before detection.
    """
    if s is None:
        return ''
    s = unicodedata.normalize('NFKC', s)
    s = (
        s.replace('’', "'")
        .replace('‘', "'")
        .replace('`', "'")
        .replace('´', "'")
        .replace('\u00a0', ' ')
        .replace('\u2007', ' ')
        .replace('\u202f', ' ')
        .replace('\u00ad', '')  # soft hyphen
    )
    # Rejoin words split across line breaks by hyphen
    s = repair_linebreak_hyphenation(s)
    # Preserve newlines; collapse only spaces/tabs
    s = re.sub(r'[ \t]+', ' ', s)
    return s.strip()


def scrub_inline(s: str) -> str:
    """
    Scrub final field values only (after detection & slicing):
    - remove markdown emphasis markers (* and _)
    - replace literal \n with a space
    - collapse whitespace including real newlines
    - normalize stray punctuation spacing without destroying refs
    """
    if s is None:
        return ''
    s = s.replace('*', '').replace('_', '')
    s = s.replace('\\n', ' ')
    s = re.sub(r'(?:\r?\n)+', ' ', s)
    # Collapse spaces
    s = re.sub(r'\s+', ' ', s).strip()
    # Fix doubled periods
    s = re.sub(r'\.{2,}', '.', s)
    # Normalize spaces around ,.;: but avoid breaking scripture refs like "Ps. 20: 7"
    # First tighten spaces before punctuation
    s = re.sub(r'\s+([,.;:])', r'\1', s)
    # Then ensure a single space after punctuation when followed by a letter/number, except colons within chapter:verse
    s = re.sub(r'([,.;])\s*', r'\1 ', s)
    # For colon, keep as-is; then fix common "Book n: m" by removing space after colon only if it's digit-digit
    s = re.sub(r'(\b\d+):\s+(\d+\b)', r'\1:\2', s)
    # Final space collapse
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def clean_reading(val: str) -> str:
    """
    Normalize extracted reading strings:
    - remove embedded real newlines
    - remove surrounding/trailing punctuation/parenthesis
    - collapse spaces
    """
    if not val:
        return ''
    val = val.replace('\n', ' ')
    val = re.sub(r'^[\s\(\[]+|[\s\)\]\.;,]+$', '', val)
    val = re.sub(r'\s+', ' ', val).strip()
    return val


def parse_subject_and_reading(subject_raw: str) -> tuple[str, Optional[str]]:
    """
    Strip leading 'Subject:' and extract '(read ...)' from the subject if present.
    Returns (clean_subject, reading or None).
    """
    if not subject_raw:
        return '', None
    m = re.match(r'^\s*Subject\s*:\s*(.*)$', subject_raw, flags=re.IGNORECASE)
    s = m.group(1) if m else subject_raw

    reading = None
    matches = list(re.finditer(r'\(([^)]*read[^)]*)\)', s, flags=re.IGNORECASE))
    if matches:
        pm = matches[-1]
        inside = pm.group(1)
        mread = re.search(r'\bread\b\s*\(?\s*(.+?)\s*\)?\s*$', inside, flags=re.IGNORECASE)
        if mread:
            reading = clean_reading(mread.group(1))
        s = (s[: pm.start()] + s[pm.end() :]).strip()

    s = scrub_inline(s)
    return s, (reading or None)


def extract_header_fields(full_text: str) -> Dict[str, str]:
    hdr = {'message_id': '', 'subject': '', 'from': '', 'to': '', 'date': ''}
    for line in full_text.splitlines():
        if line.startswith('message_id: '):
            hdr['message_id'] = line.split('message_id: ', 1)[1].strip()
        elif line.startswith('subject   : '):
            hdr['subject'] = line.split('subject   : ', 1)[1].strip()
        elif line.startswith('from      : '):
            hdr['from'] = line.split('from      : ', 1)[1].strip()
        elif line.startswith('to        : '):
            hdr['to'] = line.split('to        : ', 1)[1].strip()
        elif line.startswith('date      : '):
            hdr['date'] = line.split('date      : ', 1)[1].strip()
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
# - M/D, M/D/YY, M/D/YYYY with optional stray dot between D and year (e.g., 2/21.2019)
# - M-D, M-D-YY, M-D-YYYY
# Date variants used in verse header:
# - Month name + day (e.g., MAY 29)
# - M/D, M/D/YY, M/D/YYYY with optional stray dot between D and year (e.g., 2/21.2019)
# - M-D, M-D-YY, M-D-YYYY
DATE_NUM = r'\d{1,2}'
DATE_YEAR = r'(?:\d{2}|\d{4})'
DATE_SEP = r'[:/\.\-]'

# Build the numeric date part: M SEP D [optional SEP/stray-dot YEAR]
DATE_NUMERIC = DATE_NUM + r'\s*' + DATE_SEP + r'\s*' + DATE_NUM + r'(?:\s*(?:[.\-/:])?\s*' + DATE_YEAR + r')?'

# Full DATE variant: either "Monthname D" or numeric form
DATE_VARIANT = r'(?:[A-Z][a-z]+\s+' + DATE_NUM + r'|' + DATE_NUMERIC + r')'

# Verse header may appear as:
# - "VERSE FOR <date>:" with content optionally on same line
# - "VERSE FOR <date>" (no colon) on its own line
# - "THE VERSE FOR <date>:" typo variant
# - Optional missing space between FOR and date: "VERSE FOR2/27/2019"
VERSE_LINE_RE = re.compile(
    r'^\s*(?P<hdr>(?:THE\s+)?VERSE\s+FOR)\s*(?:' + DATE_VARIANT + r'|TODAY)\s*:?\s*(?P<after>.*)$',
    re.IGNORECASE,
)

# Inline-only form (kept for convenience when searching tail on same line)
VERSE_INLINE_RE = re.compile(
    r'(?P<verse_hdr>\b(?:THE\s+)?VERSE\s+FOR)\s*(?:' + DATE_VARIANT + r'|TODAY)\s*:\s*(?P<after>.*)',
    re.IGNORECASE,
)
# Thought header can be "THOUGHT FOR TODAY:" or "THOUGHT FOR TODAY" alone
THOUGHT_LINE_RE = re.compile(
    r"""^\s*THOUGHT\s+FOR\s+TODAY\s*:?\s*$""",
    re.IGNORECASE,
)

# Inline joined version (content after colon same line)
THOUGHT_JOIN_RE = re.compile(
    r"""\bTHOUGHT\s+FOR\s+TODAY\s*:\s*""",
    re.IGNORECASE,
)

# Signature and slight variants
PRAYER_SIGNATURE_ANY_RE = re.compile(
    r"""(^|\b)[*_"]*\s*PASTOR\s+AL\s*[*_"]*(?:[,:\-]\s*)?($|\b)""",
    re.IGNORECASE,
)

# General parenthetical capture (DOTALL for cross-line parentheses)
PAREN_DOTALL_RE = re.compile(r'\((.*?)\)', re.DOTALL)

# Flexible reading detectors
READ_INLINE_RE = re.compile(
    r"""\bread\b\s*\(?\s*([A-Za-z0-9\.\:\-\;\s,]+?)\s*\)?\b""",
    re.IGNORECASE,
)
READ_LINE_RE = re.compile(
    r"""^\s*\(*\s*read\s+([A-Za-z0-9\.\:\-\;\s,]+?)\s*\)*\s*$""",
    re.IGNORECASE,
)


def extract_reading_after_verse_header(lines: List[str], i: int) -> Optional[str]:
    """
    Given the index of the verse header line (i), scan that line and a few following lines
    to find the reading according to these rules:
      - The first parenthetical after the verse header is the scripture reference (part of the verse).
      - The second parenthetical (if present) is the reading.
      - If any parenthetical contains a READ ... clause, that parenthetical's content after READ is the reading.
      - Otherwise, standalone READ lines in the next few lines are considered.
    Returns a cleaned reading string or None.
    """
    window_lines = []
    for j in range(i, min(i + 6, len(lines))):
        window_lines.append(lines[j])
    window = '\n'.join(window_lines)

    # Collect all parentheses in order across the window
    parens = list(PAREN_DOTALL_RE.finditer(window))

    # Prefer any parenthetical that contains READ first (covers: "(READ HEB. 9:11-15)")
    for m in parens:
        inside = m.group(1)
        if re.search(r'\bread\b', inside, flags=re.IGNORECASE):
            mread = re.search(r'\bread\b\s*\(?\s*(.+?)\s*\)?\s*$', inside, flags=re.IGNORECASE)
            if mread:
                return clean_reading(mread.group(1))

    # Otherwise, if there are at least two parentheses, the second one is the reading
    if len(parens) >= 2:
        return clean_reading(parens[1].group(1))

    # If no second parenthetical, look for a standalone READ line shortly after
    for j in range(i, min(i + 6, len(lines))):
        mm = READ_LINE_RE.match(lines[j])
        if mm:
            return clean_reading(mm.group(1))

    # Also allow inline READ in a line even without parentheses
    for j in range(i, min(i + 6, len(lines))):
        mread = READ_INLINE_RE.search(lines[j])
        if mread:
            return clean_reading(mread.group(1))

    return None


def find_positions_and_reading(
    lines: List[str],
) -> tuple[Optional[int], List[int], Optional[int], Optional[str]]:
    """
    Return:
      - verse_line: line index where verse header occurs
      - thought_lines: all line indices where 'THOUGHT FOR TODAY' headers occur
      - prayer_line: line index where 'PASTOR AL' appears (if any)
      - reading: extracted following the 'second parenthesis / READ' rules
    """
    verse_line: Optional[int] = None
    thought_lines: List[int] = []
    prayer_line: Optional[int] = None
    reading: Optional[str] = None

    for i, ln in enumerate(lines):
        if verse_line is None and VERSE_LINE_RE.match(ln):
            verse_line = i
            reading = extract_reading_after_verse_header(lines, i)

        # Collect all THOUGHT headers
        if THOUGHT_LINE_RE.match(ln) or THOUGHT_JOIN_RE.search(ln):
            thought_lines.append(i)

        # Signature
        if prayer_line is None and PRAYER_SIGNATURE_ANY_RE.search(ln):
            prayer_line = i

    return verse_line, thought_lines, prayer_line, reading


def slice_sections(
    lines: List[str],
    verse_line: Optional[int],
    thought_lines: List[int],
    prayer_line: Optional[int],
) -> tuple[str, str, str]:
    """
    Slice verse/reflection/prayer blocks:

    - Verse: from verse header line's tail + subsequent lines up to first THOUGHT header.
    - Reflection: from first THOUGHT header's content/next line to prayer signature or end.
    - Prayer: from signature line onward (usually just signature, stripped).
    """
    verse_text = reflection_text = prayer_text = ''

    # Determine first thought header line if present
    first_thought_line = thought_lines[0] if thought_lines else None

    # Verse slice
    if verse_line is not None:
        chunks = []
        m_inline = VERSE_INLINE_RE.search(lines[verse_line])
        m_line = VERSE_LINE_RE.match(lines[verse_line])

        if m_inline:
            after = m_inline.group('after').strip()
            if after:
                chunks.append(after)
        elif m_line:
            after = m_line.group('after').strip()
            if after:
                chunks.append(after)

        stop_line = first_thought_line if first_thought_line is not None else len(lines)
        if verse_line + 1 < stop_line:
            between = lines[verse_line + 1 : stop_line]
            if between:
                chunks.append('\n'.join(between).strip())
        verse_text = '\n'.join([c for c in chunks if c]).strip()

    # Reflection slice: from first THOUGHT header onward
    if first_thought_line is not None:
        # Inline content after colon on the same line, if any
        inline_after = ''
        m_inline_th = THOUGHT_JOIN_RE.search(lines[first_thought_line])
        if m_inline_th:
            inline_after = lines[first_thought_line][m_inline_th.end() :].strip()

        chunks = []
        if inline_after:
            chunks.append(inline_after)

        start_idx = first_thought_line + 1
        stop_line = prayer_line if prayer_line is not None else len(lines)
        if start_idx < stop_line:
            chunks.append('\n'.join(lines[start_idx:stop_line]).strip())
        reflection_text = '\n'.join([c for c in chunks if c]).strip()

        # Remove any trailing standalone thought header that might repeat with no content
        reflection_text = re.sub(
            r'(?:^|\n)\s*THOUGHT\s+FOR\s+TODAY\s*:?\s*$',
            '',
            reflection_text,
            flags=re.IGNORECASE,
        ).strip()

        # Strip trailing "PASTOR AL" that may have leaked in
        reflection_text = re.sub(
            r'\s*[*"_]*\s*PASTOR\s+AL\s*[*"_]*\s*[,:\-]?\s*$',
            '',
            reflection_text,
            flags=re.IGNORECASE,
        ).strip()

    # Prayer slice
    if prayer_line is not None:
        prayer_block = '\n'.join(lines[prayer_line:]).strip()
        # remove leading "PASTOR AL"
        prayer_block = re.sub(
            r'^\s*[*"_]*\s*PASTOR\s+AL\s*[*"_]*\s*[,:\-]?\s*',
            '',
            prayer_block,
            flags=re.IGNORECASE,
        )
        prayer_text = prayer_block.strip()
    else:
        prayer_text = ''

    return verse_text, reflection_text, prayer_text


def parse_one(full_text: str) -> Dict[str, object]:
    hdr = extract_header_fields(full_text)
    body = normalize_keep_newlines(extract_body(full_text))
    lines = body.splitlines()

    verse_line, thought_lines, prayer_line, reading_from_body = find_positions_and_reading(lines)
    verse_raw, reflection_raw, prayer_raw = slice_sections(lines, verse_line, thought_lines, prayer_line)

    subject_clean, reading_from_subject = parse_subject_and_reading(hdr.get('subject', ''))

    # Priority: subject -> body (second parentheses or READ) -> ""
    reading_val = reading_from_subject or reading_from_body or ''

    record: Dict[str, object] = {
        'message_id': hdr.get('message_id', ''),
        'date_utc': hdr.get('date', ''),
        'subject': subject_clean,
        'verse': scrub_inline(verse_raw),
        'reflection': scrub_inline(reflection_raw),
        'prayer': scrub_inline(prayer_raw),
        'reading': reading_val,  # always present
        'original_content': body,
        'found_verse': bool(verse_raw),
        'found_reflection': bool(reflection_raw),
        'found_prayer': bool(prayer_raw),
        'found_reading': bool(reading_val),
    }

    return record


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description='Parse 1902 devotionals (robust VERSE/THOUGHT headers, signature handling, flexible date parsing)'
    )
    ap.add_argument(
        '--input-dir',
        default=DEFAULT_INPUT_DIR,
        help='Directory containing .txt messages (default: 1902)',
    )
    ap.add_argument('--out', default=OUT_JSON, help='Output JSON file (default: parsed_1902.json)')
    args = ap.parse_args()

    src = Path(args.input_dir)
    files = sorted(src.glob('*.txt'))
    if not files:
        print(f'No files found in {src.resolve()}')
        Path(args.out).write_text('[]', encoding='utf-8')
        return

    rows: List[Dict[str, object]] = []
    for fp in files:
        txt = fp.read_text(encoding='utf-8', errors='replace')
        rows.append(parse_one(txt))

    Path(args.out).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote {len(rows)} records to {Path(args.out).resolve()}')


if __name__ == '__main__':
    main()
