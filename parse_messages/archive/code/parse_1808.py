#!/usr/bin/env python3
"""
Daily Devotional Message Parser (batch 1808)

Extracts:
-    header fields (message_id, subject, from, to, date)
-    verse block
-    reflection block (Thought)
-    prayer block (Prayer)
-    optional reading (from subject '(read ...)' or body rules)

Per-batch adjustments live in BatchConfig.
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
    # I/O
    input_dir: str = '1808'
    out_json: str = 'parsed_1808.json'

    # Header/body separator string in the files
    header_body_sep: str = '=' * 67

    # Month name variants used in dates (kept for robustness if needed)
    month_abbr: str = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?'
    month_full: str = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'

    # Labels and signatures appearing in this batch
    verse_labels: List[str] = None  # patterns for verse header
    thought_labels: List[str] = None  # patterns for thought header
    prayer_labels: List[str] = None  # patterns for prayer header
    signature_phrase: str = r'PASTOR\s+AL'

    # Reading extraction window
    reading_lookahead: int = 6


def default_verse_labels() -> List[str]:
    # This batch primarily uses "VERSE FOR TODAY"
    return [
        r'(?:THE\s+)?VERSE\s+FOR\s+TODAY',
        r'(?:THE\s+)?VERSE\s+FOR',  # generic fallback to allow dates/titles if present
    ]


def default_thought_labels() -> List[str]:
    return [
        r'(?:THE\s+)?THOUGHT\s+FOR\s+TODAY',
    ]


def default_prayer_labels() -> List[str]:
    # Allow PRAYER FOR TODAY with colon or semicolon; include "PRAY FOR TODAY" typo variant
    return [
        r'PRAYER\s+FOR\s+TODAY',
        r'PRAY\s+FOR\s+TODAY',
    ]


CFG = BatchConfig()
if CFG.verse_labels is None:
    CFG.verse_labels = default_verse_labels()
if CFG.thought_labels is None:
    CFG.thought_labels = default_thought_labels()
if CFG.prayer_labels is None:
    CFG.prayer_labels = default_prayer_labels()


# =========================
# Helpers: regex builders
# =========================


def build_body_header_re(sep: str) -> re.Pattern:
    return re.compile(
        rf'^{re.escape(sep)}\s*Body \(clean, unformatted\):\s*{re.escape(sep)}\s*',
        re.MULTILINE,
    )


def build_date_patterns(cfg: BatchConfig) -> Tuple[str, str]:
    # Month name variants (kept available for robustness)
    MONTH_NAME = rf'(?:{cfg.month_abbr}|{cfg.month_full})'
    DATE_NUM = r'\d{1,2}'
    DATE_YEAR = r'(?:\d{2}|\d{4})'
    DATE_SEP = r'[:/\.\-]'

    DATE_NUMERIC = DATE_NUM + r'\s*' + DATE_SEP + r'\s*' + DATE_NUM + r'(?:\s*(?:[.\-/:])?\s*' + DATE_YEAR + r')?'

    DATE_MONTHDAY = MONTH_NAME + r'\s+' + DATE_NUM + r'(?:\s*,\s*' + DATE_YEAR + r')?'

    DATE_VARIANT = rf'(?:{DATE_MONTHDAY}|{DATE_NUMERIC})'
    return DATE_VARIANT, MONTH_NAME


def build_detection_patterns(cfg: BatchConfig) -> Dict[str, object]:
    DATE_VARIANT, _ = build_date_patterns(cfg)

    # Build multi-header detectors (lists), tolerant to underscores and optional colon/semicolon/question mark
    def compile_lines(patterns: List[str]) -> List[re.Pattern]:
        return [re.compile(rf'^\s*_*\s*{pat}\s*[:;]?\s*\??\s*_*\s*$', re.IGNORECASE) for pat in patterns]

    def compile_joins(patterns: List[str]) -> List[re.Pattern]:
        return [re.compile(rf'{pat}\s*[:;]\s*', re.IGNORECASE) for pat in patterns]

    verse_line_re_list = compile_lines(cfg.verse_labels)
    verse_join_re_list = compile_joins(cfg.verse_labels)

    thought_line_re_list = compile_lines(cfg.thought_labels)
    thought_join_re_list = compile_joins(cfg.thought_labels)

    prayer_line_re_list = compile_lines(cfg.prayer_labels)
    prayer_join_re_list = compile_joins(cfg.prayer_labels)

    # Explicit "VERSE FOR <DATE|TODAY>" on one line (capture tail)
    verse_for_line_re = re.compile(
        rf'^\s*_*\s*(?:THE\s+)?VERSE\s+FOR\s*(?:{DATE_VARIANT}|TODAY)\s*[:;]?\s*_*\s*(?P<after>.*)$',
        re.IGNORECASE,
    )

    # Signature
    prayer_signature_any_re = re.compile(
        rf'(^|\b)[*_"\s]*{cfg.signature_phrase}\s*[*_"]*(?:[,:\-]\s*)?($|\b)',
        re.IGNORECASE,
    )

    # Parentheses + reading detectors
    paren_dotall_re = re.compile(r'\((.*?)\)', re.DOTALL)
    read_inline_re = re.compile(
        r"""\bread\b\s*\(?\s*([A-Za-z0-9\.\:\-\;\s,]+?)\s*\)?\b""",
        re.IGNORECASE,
    )
    read_line_re = re.compile(
        r"""^\s*\(*\s*read\s+([A-Za-z0-9\.\:\-\;\s,]+?)\s*\)*\s*$""",
        re.IGNORECASE,
    )

    return {
        'VERSE_LINE_RE_LIST': verse_line_re_list,
        'VERSE_JOIN_RE_LIST': verse_join_re_list,
        'VERSE_FOR_LINE_RE': verse_for_line_re,
        'THOUGHT_LINE_RE_LIST': thought_line_re_list,
        'THOUGHT_JOIN_RE_LIST': thought_join_re_list,
        'PRAYER_LINE_RE_LIST': prayer_line_re_list,
        'PRAYER_JOIN_RE_LIST': prayer_join_re_list,
        'PRAYER_SIGNATURE_ANY_RE': prayer_signature_any_re,
        'PAREN_DOTALL_RE': paren_dotall_re,
        'READ_INLINE_RE': read_inline_re,
        'READ_LINE_RE': read_line_re,
    }


# =========================
# Normalization utilities
# =========================

HYPHEN_LINEBREAK_RE = re.compile(r'-\s*(?:\r?\n)+\s*')


def repair_linebreak_hyphenation(s: str) -> str:
    if not s:
        return ''
    return HYPHEN_LINEBREAK_RE.sub('', s)


def normalize_keep_newlines(s: str) -> str:
    """
    Normalize text while preserving newlines for slicing.
    Do NOT remove underscores here. Also repair hyphenation.
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
    s = repair_linebreak_hyphenation(s)
    s = re.sub(r'[ \t]+', ' ', s)  # collapse spaces but keep newlines
    return s.strip()


def scrub_inline(s: str) -> str:
    """
    Final cleanup for extracted fields:
    - remove markdown emphasis markers (* and _)
    - replace literal \n with a space
    - collapse whitespace including real newlines
    - normalize punctuation spacing without mangling scripture refs
    """
    if s is None:
        return ''
    s = s.replace('*', '').replace('_', '')
    s = s.replace('\\n', ' ')
    s = re.sub(r'(?:\r?\n)+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    # Fix duplicated punctuation
    s = re.sub(r'\.{2,}', '.', s)
    s = re.sub(r'__+', '_', s)
    # Tighten spaces before punctuation
    s = re.sub(r'\s+([,.;:])', r'\1', s)
    # Add a single space after punctuation (except colon inside chapter:verse)
    s = re.sub(r'([,.;])\s*', r'\1 ', s)
    s = re.sub(r'(\b\d+):\s+(\d+\b)', r'\1:\2', s)  # 20: 7 -> 20:7
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def clean_reading(val: str) -> str:
    if not val:
        return ''
    val = val.replace('\n', ' ')
    val = re.sub(r'^[\s\(\[]+|[\s\)\]\.;,]+$', '', val)
    val = re.sub(r'\s+', ' ', val).strip()
    return val


# =========================
# Header/body extraction
# =========================


def extract_header_fields(full_text: str, cfg: BatchConfig) -> Dict[str, str]:
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
        if line.strip() == cfg.header_body_sep:
            break
    return hdr


def extract_body(full_text: str, cfg: BatchConfig) -> str:
    body_header_re = build_body_header_re(cfg.header_body_sep)
    m = body_header_re.search(full_text)
    if m:
        return full_text[m.end() :].strip()
    parts = full_text.split(cfg.header_body_sep)
    if len(parts) >= 3:
        return (cfg.header_body_sep.join(parts[2:])).strip()
    return full_text.strip()


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


# =========================
# Detection utilities
# =========================


def line_matches_any(line: str, patterns: List[re.Pattern]) -> bool:
    return any(p.match(line) for p in patterns)


def find_join_tail(line: str, join_patterns: List[re.Pattern]) -> str:
    for p in join_patterns:
        m = p.search(line)
        if m:
            return line[m.end() :].strip()
    return ''


# =========================
# Detection and slicing
# =========================


def extract_reading_after_verse_header(
    lines: List[str], i: int, pats: Dict[str, object], lookahead: int
) -> Optional[str]:
    window_lines = []
    for j in range(i, min(i + lookahead, len(lines))):
        window_lines.append(lines[j])
    window = '\n'.join(window_lines)

    parens = list(pats['PAREN_DOTALL_RE'].finditer(window))

    # Prefer any parenthetical that contains READ
    for m in parens:
        inside = m.group(1)
        if re.search(r'\bread\b', inside, flags=re.IGNORECASE):
            mread = re.search(r'\bread\b\s*\(?\s*(.+?)\s*\)?\s*$', inside, flags=re.IGNORECASE)
            if mread:
                return clean_reading(mread.group(1))

    # Otherwise, if there are at least two parentheses, the second one is the reading
    if len(parens) >= 2:
        return clean_reading(parens[1].group(1))

    # Standalone READ line
    for j in range(i, min(i + lookahead, len(lines))):
        mm = pats['READ_LINE_RE'].match(lines[j])
        if mm:
            return clean_reading(mm.group(1))

    # Inline READ without parentheses
    for j in range(i, min(i + lookahead, len(lines))):
        mread = pats['READ_INLINE_RE'].search(lines[j])
        if mread:
            return clean_reading(mread.group(1))

    return None


def find_positions_and_reading(
    lines: List[str], pats: Dict[str, object], cfg: BatchConfig
) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[str]]:
    """
    Returns:
      - verse_line: index of verse header or None
      - thought_line: index of thought header or None
      - prayer_line: index of prayer header or None
      - signature_line: index of signature line ('PASTOR AL') or None
      - reading: reading parsed near verse header (or None)
    """
    verse_line = None
    thought_line = None
    prayer_line = None
    signature_line = None
    reading = None

    for i, ln in enumerate(lines):
        # Verse header detection
        if verse_line is None:
            if line_matches_any(ln, pats['VERSE_LINE_RE_LIST']) or pats['VERSE_FOR_LINE_RE'].match(ln):
                verse_line = i
                reading = extract_reading_after_verse_header(lines, i, pats, cfg.reading_lookahead)

        # Thought header detection
        if thought_line is None and line_matches_any(ln, pats['THOUGHT_LINE_RE_LIST']):
            thought_line = i

        # Prayer header detection (allow 'PRAYER' and 'PRAY' variants)
        if prayer_line is None and line_matches_any(ln, pats['PRAYER_LINE_RE_LIST']):
            prayer_line = i

        # Signature detection
        if signature_line is None and pats['PRAYER_SIGNATURE_ANY_RE'].search(ln):
            signature_line = i

    return verse_line, thought_line, prayer_line, signature_line, reading


def slice_sections(
    lines: List[str],
    verse_line: Optional[int],
    thought_line: Optional[int],
    prayer_line: Optional[int],
    signature_line: Optional[int],
    pats: Dict[str, object],
) -> tuple[str, str, str]:
    """
    Slice blocks:
      - Verse: from verse header line forward to the first of thought/prayer/signature/end.
      - Reflection: from thought header's content/next line up to prayer header or signature or end.
      - Prayer: from prayer header content to signature/end. If no prayer header but signature exists,
                prayer will be empty (signature-only signoff).
    """
    verse_text = reflection_text = prayer_text = ''

    # Verse slice
    if verse_line is not None:
        stop_candidates = [idx for idx in [thought_line, prayer_line, signature_line] if idx is not None]
        stop_line = min(stop_candidates) if stop_candidates else len(lines)
        chunks: List[str] = []

        # Inline tail after header (e.g., "VERSE FOR TODAY: <tail>")
        tail = find_join_tail(lines[verse_line], pats['VERSE_JOIN_RE_LIST'])
        if not tail:
            m_inline = pats['VERSE_FOR_LINE_RE'].match(lines[verse_line])
            if m_inline:
                tail = (m_inline.groupdict().get('after') or '').strip()
        if tail:
            chunks.append(tail)

        nxt = verse_line + 1
        if nxt < stop_line:
            chunks.append('\n'.join(lines[nxt:stop_line]).strip())

        verse_text = '\n'.join([c for c in chunks if c]).strip()

    # Reflection slice
    if thought_line is not None:
        stop_line = min(
            [idx for idx in [prayer_line, signature_line] if idx is not None],
            default=len(lines),
        )
        chunks: List[str] = []

        inline_after = find_join_tail(lines[thought_line], pats['THOUGHT_JOIN_RE_LIST'])
        if inline_after:
            chunks.append(inline_after)
        start_idx = thought_line + 1
        if start_idx < stop_line:
            chunks.append('\n'.join(lines[start_idx:stop_line]).strip())

        reflection_text = '\n'.join([c for c in chunks if c]).strip()

        # Remove accidental trailing header
        reflection_text = re.sub(
            r'(?:^|\n)\s*_*\s*(?:THE\s+)?THOUGHT\s+FOR\s+(?:TODAY|[A-Z][A-Za-z\.]+\s+\d{1,2}(?:\s*,\s*(?:\d{2}|\d{4}))?)\s*[:;]?\s*_*\s*$',
            '',
            reflection_text,
            flags=re.IGNORECASE,
        ).strip()
        # Strip signature if leaked
        reflection_text = re.sub(
            r'\s*[*"_\s]*PASTOR\s+AL\s*[*"_]*\s*[,:\-]?\s*$',
            '',
            reflection_text,
            flags=re.IGNORECASE,
        ).strip()

    # Prayer slice
    if prayer_line is not None:
        stop_line = signature_line if signature_line is not None else len(lines)
        chunks: List[str] = []

        inline_after = find_join_tail(lines[prayer_line], pats['PRAYER_JOIN_RE_LIST'])
        if inline_after:
            chunks.append(inline_after)

        start_idx = prayer_line + 1
        if start_idx < stop_line:
            chunks.append('\n'.join(lines[start_idx:stop_line]).strip())

        prayer_text = '\n'.join([c for c in chunks if c]).strip()
    else:
        prayer_text = ''

    return verse_text, reflection_text, prayer_text


# =========================
# Record assembly
# =========================


def parse_one(full_text: str, cfg: BatchConfig) -> Dict[str, object]:
    pats = build_detection_patterns(cfg)

    hdr = extract_header_fields(full_text, cfg)
    body = normalize_keep_newlines(extract_body(full_text, cfg))
    lines = body.splitlines()

    verse_line, thought_line, prayer_line, signature_line, reading_from_body = find_positions_and_reading(
        lines, pats, cfg
    )
    verse_raw, reflection_raw, prayer_raw = slice_sections(
        lines, verse_line, thought_line, prayer_line, signature_line, pats
    )

    subject_clean, reading_from_subject = parse_subject_and_reading(hdr.get('subject', ''))

    # Priority: subject -> body (second-parenthesis / READ) -> ""
    reading_val = reading_from_subject or reading_from_body or ''

    record: Dict[str, object] = {
        'message_id': hdr.get('message_id', ''),
        'date_utc': hdr.get('date', ''),
        'subject': subject_clean,
        'verse': scrub_inline(verse_raw),
        'reflection': scrub_inline(reflection_raw),
        'prayer': scrub_inline(prayer_raw),
        'reading': reading_val,
        'original_content': body,
        'found_verse': bool(verse_raw),
        'found_reflection': bool(reflection_raw),
        'found_prayer': bool(prayer_raw),
        'found_reading': bool(reading_val),
    }
    return record


# =========================
# CLI
# =========================


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description='Parse devotionals (batch-configurable headers, date parsing, and signature/prayer handling)'
    )
    ap.add_argument(
        '--input-dir',
        default=BatchConfig().input_dir,
        help='Directory containing .txt messages (default: 1808)',
    )
    ap.add_argument(
        '--out',
        default=BatchConfig().out_json,
        help='Output JSON file (default: parsed_1808.json)',
    )
    args = ap.parse_args()

    # Apply CLI overrides to the config
    cfg = BatchConfig(
        input_dir=args.input_dir,
        out_json=args.out,
        header_body_sep=CFG.header_body_sep,
        month_abbr=CFG.month_abbr,
        month_full=CFG.month_full,
        verse_labels=CFG.verse_labels,
        thought_labels=CFG.thought_labels,
        prayer_labels=CFG.prayer_labels,
        signature_phrase=CFG.signature_phrase,
        reading_lookahead=CFG.reading_lookahead,
    )

    src = Path(cfg.input_dir)
    files = sorted(src.glob('*.txt'))
    if not files:
        print(f'No files found in {src.resolve()}')
        Path(cfg.out_json).write_text('[]', encoding='utf-8')
        return

    rows: List[Dict[str, object]] = []
    for fp in files:
        txt = fp.read_text(encoding='utf-8', errors='replace')
        rows.append(parse_one(txt, cfg))

    Path(cfg.out_json).write_text(
        json.dumps(rows, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    print(f'Wrote {len(rows)} records to {Path(cfg.out_json).resolve()}')


if __name__ == '__main__':
    main()
