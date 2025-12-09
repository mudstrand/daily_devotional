#!/usr/bin/env python3
import re
import json
import unicodedata
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

# Outputs
AUTO_CORPORA_JSON = Path('auto_corpora.json')
GENERATED_PROFILE_JSON = Path('generated_profile.json')
CORPUS_PREVIEW_JSON = Path('corpus_preview.json')
HANDLED_IDS = Path('handled_profile.ids')

# Header/body split markers from your saved export
HDR_BODY_SEP = '=' * 67
BODY_HEADER_RE = re.compile(
    rf'^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*',
    re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description='Auto-discover a consistent corpus of messages and generate a parsing profile (with prayer inference).'
    )
    p.add_argument(
        '--input-dir',
        required=True,
        help="Directory with saved message .txt files (e.g., 'missing', '2106').",
    )
    p.add_argument('--top-n', type=int, default=5, help='How many clusters to report (default: 5).')
    p.add_argument(
        '--preview',
        type=int,
        default=10,
        help='How many samples in preview JSON (default: 10).',
    )
    p.add_argument('--pattern', default='*.txt', help='Glob for files (default: *.txt).')
    p.add_argument('--debug', action='store_true', help='Print debug info for first few misses.')
    return p.parse_args()


# Normalization
def normalize(s: str) -> str:
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
    s = re.sub(r'[ \t]+', ' ', s)
    return s.strip()


# Extract header/body
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


# Heading-ish line (title-like), optional trailing colon
HEADING_LINE_RE = re.compile(r'^\s*(?P<h>[^\n\r]{2,}?)(?::)?\s*$')

# Semantic classifiers
VERSE_HEAD_RE = re.compile(r'\b(verse|verses|scripture|text|reading|meditation)\b', re.IGNORECASE)
REFLECT_HEAD_RE = re.compile(
    r'\b(thought|thoughts|reflection|reflections|devotional|lesson|lessons|meditation)\b',
    re.IGNORECASE,
)
PRAYER_HEAD_RE = re.compile(r'\b(prayer|prayers|prayer suggestion|suggested prayer)\b', re.IGNORECASE)

# Prayer inference proxies (no explicit 'Prayer:' heading)
PRAYER_OPENERS_RE = re.compile(
    r'^\s*(dear\s+(heavenly\s+)?father|dear\s+lord|heavenly\s+father|lord\s+jesus)\b',
    re.IGNORECASE,
)
PRAYER_SIGNATURES_RE = re.compile(
    r'^\s*(pastor\s+(alvin\s+and\s+marcie\s+)?sather)\s*\*?$',
    re.IGNORECASE,
)
PRAYER_AMEN_RE = re.compile(r'\bamen\.?\s*$', re.IGNORECASE)

# Terminators (also used to cap prayer)
DEFAULT_TERMINATORS = [
    r'Pastor\s+Alvin\s+and\s+Marcie\s+Sather',
    r'Amen\.?$',
]


def find_headings(lines: List[str]) -> List[Tuple[int, str]]:
    out = []
    for i, ln in enumerate(lines):
        m = HEADING_LINE_RE.match(ln)
        if m:
            h = m.group('h').strip()
            if 2 <= len(h) <= 200:
                out.append((i, h))
    return out


def classify_heading(h: str) -> Optional[str]:
    if VERSE_HEAD_RE.search(h):
        return 'verse'
    if REFLECT_HEAD_RE.search(h):
        return 'reflection'
    if PRAYER_HEAD_RE.search(h):
        return 'prayer'
    return None


def find_triple_positions_with_inferred_prayer(lines: List[str]) -> Dict[str, int]:
    """
    Find verse, reflection headings; infer prayer start if:
      - explicit prayer heading, OR
      - a prayer-opener line, OR
      - a signature line, OR
      - (fallback) the first line after reflection that ends with 'Amen.'
    """
    heads = find_headings(lines)
    pos: Dict[str, int] = {}

    # Verse first
    v_idx = None
    for i, h in heads:
        if classify_heading(h) == 'verse':
            v_idx = i
            pos['verse'] = i
            break
    if v_idx is None:
        return pos

    # Reflection after verse
    r_idx = None
    for i, h in heads:
        if i <= v_idx:
            continue
        if classify_heading(h) == 'reflection':
            r_idx = i
            pos['reflection'] = i
            break
    if r_idx is None:
        return pos

    # Prayer explicit heading after reflection
    for i, h in heads:
        if i <= r_idx:
            continue
        if classify_heading(h) == 'prayer':
            pos['prayer'] = i
            return pos

    # Prayer inference: scan lines after reflection for openers/signatures/Amen
    for i in range(r_idx + 1, len(lines)):
        ln = lines[i]
        if PRAYER_OPENERS_RE.match(ln) or PRAYER_SIGNATURES_RE.match(ln):
            pos['prayer'] = i
            return pos

    # If we didn't find an opener or signature, try to infer from 'Amen.' near the end:
    for i in range(len(lines) - 1, r_idx, -1):
        if PRAYER_AMEN_RE.search(lines[i]):
            # Heuristic: treat the paragraph containing Amen as prayer
            # Find the start of that paragraph (previous blank line)
            start = i
            j = i
            while j > r_idx + 1 and lines[j - 1].strip():
                j -= 1
            pos['prayer'] = j
            return pos

    return pos


def slice_until(lines: List[str], start_idx: int, stop_idx: Optional[int]) -> str:
    stop = stop_idx if stop_idx is not None else len(lines)
    return '\n'.join(lines[start_idx + 1 : stop]).strip()


def signature_from_headings(lines: List[str], pos: Dict[str, int]) -> Optional[Tuple[str, str, str]]:
    if not {'verse', 'reflection', 'prayer'}.issubset(pos.keys()):
        return None
    v = lines[pos['verse']].rstrip(':').strip()
    r = lines[pos['reflection']].rstrip(':').strip()
    p = lines[pos['prayer']].rstrip(':').strip()

    def norm(h: str) -> str:
        h2 = re.sub(r"\b(today|today'?s|for today)\b", '', h, flags=re.I)
        h2 = re.sub(r'\s+', ' ', h2)
        return h2.strip().lower()

    return (norm(v), norm(r), norm(p))


def derive_regex_from_signatures(sigs: List[Tuple[str, str, str]]) -> Dict[str, str]:
    verse_tokens, refl_tokens, prayer_tokens = set(), set(), set()
    for v, r, p in sigs:
        verse_tokens.update([t for t in re.findall(r'[a-z]+', v) if len(t) >= 3])
        refl_tokens.update([t for t in re.findall(r'[a-z]+', r) if len(t) >= 3])
        prayer_tokens.update([t for t in re.findall(r'[a-z]+', p) if len(t) >= 3])

    def filter_role(tokens: set[str], role: str) -> List[str]:
        role_whitelist = {
            'verse': {'verse', 'verses', 'scripture', 'text', 'reading', 'meditation'},
            'reflection': {
                'thought',
                'thoughts',
                'reflection',
                'reflections',
                'devotional',
                'lesson',
                'lessons',
                'meditation',
            },
            'prayer': {
                'prayer',
                'prayers',
                'suggestion',
                'pastor',
            },  # include 'pastor' to allow signature-start
        }
        useful = [t for t in tokens if t in role_whitelist[role]]
        if role == 'verse' and not useful:
            useful = ['verse', 'verses', 'scripture', 'reading', 'meditation', 'text']
        if role == 'reflection' and not useful:
            useful = [
                'thought',
                'thoughts',
                'reflection',
                'reflections',
                'devotional',
                'lesson',
                'lessons',
                'meditation',
            ]
        if role == 'prayer' and not useful:
            useful = ['prayer', 'prayers', 'suggestion', 'pastor']
        return sorted(set(useful))

    v_words = filter_role(verse_tokens, 'verse')
    r_words = filter_role(refl_tokens, 'reflection')
    p_words = filter_role(prayer_tokens, 'prayer')

    APO = r"[’'`´]?"

    def build(alt_words: List[str]) -> str:
        kw_alt = '|'.join(re.escape(w) for w in alt_words)
        return rf'^\s*(?:Today{APO}s?\s+|Our\s+)?(?:{kw_alt})(?:\s+for\s+Today)?\s*:\s*(?P<inline>.*)$'

    return {
        'verse_pattern': build(v_words),
        'reflection_pattern': build(r_words),
        # We’ll still generate a prayer heading pattern, but also rely on inference at run-time
        'prayer_pattern': build(p_words),
    }


def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    files = sorted(input_dir.glob(args.pattern))
    if not files:
        print(f'No files found in {input_dir.resolve()} matching {args.pattern}')
        AUTO_CORPORA_JSON.write_text('[]', encoding='utf-8')
        return

    clusters = defaultdict(list)
    top_n = max(1, args.top_n)
    preview_n = max(1, args.preview)

    DEBUG_LIMIT = 5
    debug_shown = 0

    complete_count = 0

    for fp in files:
        txt = fp.read_text(encoding='utf-8', errors='replace')
        hdr = extract_header_fields(txt)
        body = extract_body(txt)
        lines = normalize(body).splitlines()

        pos = find_triple_positions_with_inferred_prayer(lines)
        complete = {'verse', 'reflection', 'prayer'}.issubset(pos.keys())

        if complete:
            complete_count += 1
            sig = signature_from_headings(lines, pos)
            if sig:
                clusters[sig].append(
                    {
                        'path': str(fp),
                        'message_id': hdr.get('message_id', ''),
                        'date': hdr.get('date', ''),
                        'subject': hdr.get('subject', ''),
                    }
                )
        else:
            if args.debug and debug_shown < DEBUG_LIMIT:
                debug_shown += 1
                print('=' * 72)
                print(f'MISS: {fp.name}')
                print('First 20 normalized lines:')
                for ln in lines[:20]:
                    print('  ', ln)

    # Rank clusters
    ranked = sorted(
        ((sig, len(clusters[sig])) for sig in clusters),
        key=lambda x: x[1],
        reverse=True,
    )
    auto_report = []
    for sig, cnt in ranked[:top_n]:
        v, r, p = sig
        sample = clusters[sig][:preview_n]
        auto_report.append(
            {
                'signature': {'verse': v, 'reflection': r, 'prayer': p},
                'count': cnt,
                'sample_ids': [s['message_id'] for s in sample],
                'sample_subjects': [s['subject'] for s in sample],
            }
        )
    AUTO_CORPORA_JSON.write_text(json.dumps(auto_report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote auto corpora summary: {AUTO_CORPORA_JSON.resolve()}')
    print(f'Complete triples (with inferred prayer) found: {complete_count}')

    if not ranked:
        print('No clusters with complete triples (with inference) were found in this directory.')
        return

    # Build profile from best cluster
    best_sig, best_count = ranked[0]
    best_records = clusters[best_sig]
    rx_map = derive_regex_from_signatures([best_sig])

    profile = {
        'name': 'generated_profile_auto',
        'verse_pattern': rx_map['verse_pattern'],
        'reflection_pattern': rx_map['reflection_pattern'],
        'prayer_pattern': rx_map['prayer_pattern'],  # may or may not be used; we’ll infer at parse-time too
        'terminators': DEFAULT_TERMINATORS,
        'inference': {
            'allow_prayer_inference': True,
            'openers': PRAYER_OPENERS_RE.pattern,
            'signatures': PRAYER_SIGNATURES_RE.pattern,
            'amen': PRAYER_AMEN_RE.pattern,
        },
    }
    GENERATED_PROFILE_JSON.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote generated profile: {GENERATED_PROFILE_JSON.resolve()}')

    # Preview slices for a sample of the best cluster
    preview = []
    handled_ids = []
    for rec in best_records[:preview_n]:
        fp = Path(rec['path'])
        txt = fp.read_text(encoding='utf-8', errors='replace')
        hdr = extract_header_fields(txt)
        body = extract_body(txt)
        lines = normalize(body).splitlines()

        pos = find_triple_positions_with_inferred_prayer(lines)
        if not {'verse', 'reflection', 'prayer'}.issubset(pos.keys()):
            continue

        verse = slice_until(lines, pos['verse'], pos.get('reflection'))
        reflection = slice_until(lines, pos['reflection'], pos.get('prayer'))
        # For prayer, cap at terminators if present
        stop = None
        term_res = [re.compile(t, re.I) for t in DEFAULT_TERMINATORS]
        for i in range(pos['prayer'] + 1, len(lines)):
            if any(rx.search(lines[i]) for rx in term_res):
                stop = i
                break
        prayer = slice_until(lines, pos['prayer'], stop)

        preview.append(
            {
                'message_id': hdr.get('message_id', ''),
                'date_utc': hdr.get('date', ''),
                'subject': hdr.get('subject', ''),
                'verse': verse,
                'reflection': reflection,
                'prayer': prayer,
                'original_content': '\n'.join(lines),
            }
        )
        if hdr.get('message_id'):
            handled_ids.append(hdr['message_id'])

    CORPUS_PREVIEW_JSON.write_text(json.dumps(preview, indent=2, ensure_ascii=False), encoding='utf-8')
    HANDLED_IDS.write_text('\n'.join(handled_ids) + ('\n' if handled_ids else ''), encoding='utf-8')
    print(f'Wrote preview JSON: {CORPUS_PREVIEW_JSON.resolve()} ({len(preview)} samples)')
    print(f'Wrote handled IDs: {HANDLED_IDS.resolve()} ({len(handled_ids)} ids)')


if __name__ == '__main__':
    main()
