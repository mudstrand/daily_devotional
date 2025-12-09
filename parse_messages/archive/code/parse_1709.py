#!/usr/bin/env python3
"""
Daily Devotional Message Parser (batch 1709)

Handles both full VERSE/THOUGHT/PRAYER messages and short
“Thought for the day” notes without explicit headers.

Extracts:
-    header fields (message_id, subject, from, to, date)
-    verse block
-    reflection block
-    prayer block
-    optional reading (not common here)
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
    input_dir: str = '1709'
    out_json: str = 'parsed_1709.json'

    header_body_sep: str = '=' * 67

    month_abbr: str = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?'
    month_full: str = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'

    verse_labels: List[str] = None
    thought_labels: List[str] = None
    prayer_labels: List[str] = None
    signature_phrase: str = r'PASTOR\s+AL'

    reading_lookahead: int = 6


def default_verse_labels() -> List[str]:
    return [
        r'(?:THE\s+)?VERSE[S]?\s+FOR\s+TODAY',
        r'(?:THE\s+)?VERSE[S]?\s+FOR',
    ]


def default_thought_labels() -> List[str]:
    return [
        r'(?:THE\s+)?THOUGHT\s+FOR\s+TODAY',
        r'(?:THE\s+)?THOUGHT\s+FOR\s+THE\s+DAY',
        r'THOUGHT\s*:',  # short “THOUGHT:” line
    ]


def default_prayer_labels() -> List[str]:
    return [
        r'PRAYER\s+FOR\s+TODAY',
        r'PRAYER\s+FOR\s+THE\s+DAY',
        r'PRAYER\s*:',  # short “PRAYER:” line
        r'PRAYER\s+FOR\s+TODAY\.',  # trailing period variant
        r'PRAYER\s+FOR\s+TODAY\s*$',  # missing colon
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


def build_detection_patterns(cfg: BatchConfig) -> Dict[str, object]:
    # Label detectors (underscore/colon tolerant)
    def compile_lines(patterns: List[str]) -> List[re.Pattern]:
        return [re.compile(rf'^\s*_*\s*{pat}\s*[:;.]?\s*\??\s*_*\s*$', re.IGNORECASE) for pat in patterns]

    def compile_joins(patterns: List[str]) -> List[re.Pattern]:
        return [re.compile(rf'{pat}\s*[:;.]?\s*', re.IGNORECASE) for pat in patterns]

    verse_line_re_list = compile_lines(cfg.verse_labels)
    verse_join_re_list = compile_joins(cfg.verse_labels)

    thought_line_re_list = compile_lines(cfg.thought_labels)
    thought_join_re_list = compile_joins(cfg.thought_labels)

    prayer_line_re_list = compile_lines(cfg.prayer_labels)
    prayer_join_re_list = compile_joins(cfg.prayer_labels)

    # Signature
    prayer_signature_any_re = re.compile(
        rf'(^|\b)[*_"\s]*{cfg.signature_phrase}\s*[*_"]*(?:[,:\-]\s*)?($|\b)',
        re.IGNORECASE,
    )

    # Parentheses + reading detectors (kept for parity)
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
        .replace('\u00ad', '')
    )
    s = repair_linebreak_hyphenation(s)
    s = re.sub(r'[ \t]+', ' ', s)
    return s.strip()


def scrub_inline(s: str) -> str:
    if s is None:
        return ''
    s = s.replace('*', '').replace('_', '')
    s = s.replace('\\n', ' ')
    s = re.sub(r'(?:\r?\n)+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\.{2,}', '.', s)
    s = re.sub(r'__+', '_', s)
    s = re.sub(r'\s+([,.;:])', r'\1', s)
    s = re.sub(r'([,.;])\s*', r'\1 ', s)
    s = re.sub(r'(\b\d+):\s+(\d+\b)', r'\1:\2', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


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


# =========================
# Heuristics for “Thought for the day” (no explicit headers)
# =========================

SCRIPTURE_REF_RE = re.compile(r'\(([1-3]?\s?[A-Za-z][A-Za-z\.]*\s*\d+[:\.]\d+[A-Za-z0-9\-\s,]*?)\)\s*$')
QUOTED_LINE_RE = re.compile(r'[\"“].*[\"”]')


def looks_like_scripture_line(line: str) -> bool:
    ln = line.strip()
    if not ln:
        return False
    # underscore emphasis common in samples
    ln_plain = ln.strip('_ ').strip()
    return bool(SCRIPTURE_REF_RE.search(ln_plain)) or bool(QUOTED_LINE_RE.search(ln_plain))


def fallback_slice_thought_style(body: str) -> tuple[str, str, str]:
    """
    For bodies without VERSE/THOUGHT/PRAYER headers:
    - pick the first line that looks scripture-like as verse (plus next line if it contains only a reference or continuation)
    - everything else becomes reflection
    - prayer empty
    """
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return '', '', ''
    verse_lines: List[str] = []
    rest_lines: List[str] = []

    idx_script = None
    for i, ln in enumerate(lines):
        if looks_like_scripture_line(ln):
            idx_script = i
            break

    if idx_script is not None:
        verse_lines.append(lines[idx_script])
        # include an immediate next line if it's a parenthetical-only reference or continuation with heavy underscores
        if idx_script + 1 < len(lines):
            nxt = lines[idx_script + 1].strip()
            if SCRIPTURE_REF_RE.search(nxt) or nxt.startswith('_'):
                verse_lines.append(lines[idx_script + 1])
        rest_lines = lines[:idx_script] + lines[idx_script + len(verse_lines) :]
    else:
        # no obvious scripture line; put first non-empty line as "verse"
        verse_lines = [lines[0]]
        rest_lines = lines[1:]

    verse = '\n'.join(verse_lines).strip()
    reflection = '\n'.join(rest_lines).strip()
    prayer = ''
    return verse, reflection, prayer


# =========================
# Detection and slicing (full header flow)
# =========================


def build_detection_patterns(cfg: BatchConfig) -> Dict[str, object]:  # type: ignore[override]
    return _DETECTION_CACHE.setdefault('pats', _make_pats(cfg))


_DETECTION_CACHE: Dict[str, object] = {}


def _make_pats(cfg: BatchConfig) -> Dict[str, object]:
    # reuse earlier builder
    return _make_pats_impl(cfg)


def _make_pats_impl(cfg: BatchConfig) -> Dict[str, object]:
    # (inline copy of builder from above to allow caching)
    def compile_lines(patterns: List[str]) -> List[re.Pattern]:
        return [re.compile(rf'^\s*_*\s*{pat}\s*[:;.]?\s*\??\s*_*\s*$', re.IGNORECASE) for pat in patterns]

    def compile_joins(patterns: List[str]) -> List[re.Pattern]:
        return [re.compile(rf'{pat}\s*[:;.]?\s*', re.IGNORECASE) for pat in patterns]

    verse_line_re_list = compile_lines(CFG.verse_labels)
    verse_join_re_list = compile_joins(CFG.verse_labels)
    thought_line_re_list = compile_lines(CFG.thought_labels)
    thought_join_re_list = compile_joins(CFG.thought_labels)
    prayer_line_re_list = compile_lines(CFG.prayer_labels)
    prayer_join_re_list = compile_joins(CFG.prayer_labels)
    prayer_signature_any_re = re.compile(
        rf'(^|\b)[*_"\s]*{CFG.signature_phrase}\s*[*_"]*(?:[,:\-]\s*)?($|\b)',
        re.IGNORECASE,
    )
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
        'THOUGHT_LINE_RE_LIST': thought_line_re_list,
        'THOUGHT_JOIN_RE_LIST': thought_join_re_list,
        'PRAYER_LINE_RE_LIST': prayer_line_re_list,
        'PRAYER_JOIN_RE_LIST': prayer_join_re_list,
        'PRAYER_SIGNATURE_ANY_RE': prayer_signature_any_re,
        'PAREN_DOTALL_RE': paren_dotall_re,
        'READ_INLINE_RE': read_inline_re,
        'READ_LINE_RE': read_line_re,
    }


def line_matches_any(line: str, patterns: List[re.Pattern]) -> bool:
    return any(p.match(line) for p in patterns)


def find_join_tail(line: str, join_patterns: List[re.Pattern]) -> str:
    for p in join_patterns:
        m = p.search(line)
        if m:
            return line[m.end() :].strip()
    return ''


def slice_with_headers(body: str, pats: Dict[str, object], cfg: BatchConfig) -> tuple[str, str, str, bool]:
    lines = body.splitlines()
    verse_line = thought_line = prayer_line = signature_line = None

    for i, ln in enumerate(lines):
        if verse_line is None and (line_matches_any(ln, pats['VERSE_LINE_RE_LIST'])):
            verse_line = i
        if thought_line is None and line_matches_any(ln, pats['THOUGHT_LINE_RE_LIST']):
            thought_line = i
        if prayer_line is None and line_matches_any(ln, pats['PRAYER_LINE_RE_LIST']):
            prayer_line = i
        if signature_line is None and pats['PRAYER_SIGNATURE_ANY_RE'].search(ln):
            signature_line = i

    if verse_line is None and thought_line is None and prayer_line is None:
        return '', '', '', False

    def join_after(idx: Optional[int], joiners: List[re.Pattern]) -> str:
        if idx is None:
            return ''
        return find_join_tail(lines[idx], joiners)

    verse_text = ''
    reflection_text = ''
    prayer_text = ''

    # Verse
    if verse_line is not None:
        after = join_after(verse_line, pats['VERSE_JOIN_RE_LIST'])
        stop = min([i for i in [thought_line, prayer_line, signature_line] if i is not None] or [len(lines)])
        chunks = [after] if after else []
        if verse_line + 1 < stop:
            chunks.append('\n'.join(lines[verse_line + 1 : stop]).strip())
        verse_text = '\n'.join([c for c in chunks if c]).strip()

    # Reflection
    if thought_line is not None:
        after = join_after(thought_line, pats['THOUGHT_JOIN_RE_LIST'])
        stop = min([i for i in [prayer_line, signature_line] if i is not None] or [len(lines)])
        chunks = [after] if after else []
        start = thought_line + 1
        if start < stop:
            chunks.append('\n'.join(lines[start:stop]).strip())
        reflection_text = '\n'.join([c for c in chunks if c]).strip()

    # Prayer
    if prayer_line is not None:
        after = join_after(prayer_line, pats['PRAYER_JOIN_RE_LIST'])
        stop = signature_line if signature_line is not None else len(lines)
        chunks = [after] if after else []
        start = prayer_line + 1
        if start < stop:
            chunks.append('\n'.join(lines[start:stop]).strip())
        prayer_text = '\n'.join([c for c in chunks if c]).strip()

    return verse_text, reflection_text, prayer_text, True


# =========================
# Record assembly
# =========================


def parse_one(full_text: str, cfg: BatchConfig) -> Dict[str, object]:
    pats = build_detection_patterns(cfg)

    hdr = extract_header_fields(full_text, cfg)
    raw_body = extract_body(full_text, cfg)
    body = normalize_keep_newlines(raw_body)

    # Try header-based slicing first
    verse_raw, reflection_raw, prayer_raw, had_headers = slice_with_headers(body, pats, cfg)

    # Fallback to “thought style” heuristic if no headers found
    if not had_headers:
        verse_raw, reflection_raw, prayer_raw = fallback_slice_thought_style(body)

    record: Dict[str, object] = {
        'message_id': hdr.get('message_id', ''),
        'date_utc': hdr.get('date', ''),
        'subject': scrub_inline(hdr.get('subject', '')),
        'verse': scrub_inline(verse_raw),
        'reflection': scrub_inline(reflection_raw),
        'prayer': scrub_inline(prayer_raw),
        'reading': '',
        'original_content': body,
        'found_verse': bool(verse_raw),
        'found_reflection': bool(reflection_raw),
        'found_prayer': bool(prayer_raw),
        'found_reading': False,
    }
    return record


# =========================
# CLI
# =========================


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse 1709 devotionals (supports full headers and short 'Thought for the day' notes)"
    )
    ap.add_argument(
        '--input-dir',
        default=CFG.input_dir,
        help='Directory with .txt messages (default: 1709)',
    )
    ap.add_argument('--out', default=CFG.out_json, help='Output JSON (default: parsed_1709.json)')
    args = ap.parse_args()

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

    Path(cfg.out_json).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote {len(rows)} records to {Path(cfg.out_json).resolve()}')


if __name__ == '__main__':
    main()
