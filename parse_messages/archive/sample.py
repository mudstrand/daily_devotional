#!/usr/bin/env python3
import re
import csv
import json
import unicodedata
from pathlib import Path
from typing import List, Dict, Optional, Tuple

INPUT_DIR = Path('missing')
OUT_JSON = Path('parsed_semantic.json')
OUT_CSV = Path('parsed_semantic.csv')
OUT_IDS = Path('matched_semantic_ids.txt')

HDR_BODY_SEP = '=' * 67
BODY_HEADER_RE = re.compile(
    rf'^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*',
    re.MULTILINE,
)


# Normalize for robust matching
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


# Extract header and body from the saved txt format
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


# Detect heading lines (allow optional colon; we’ll still prefer those ending in colon)
HEADING_RE = re.compile(r'^\s*(?P<h>[^:\n\r]{2,})(?::)?\s*$')

# Semantic classifiers (adjustable)
VERSE_HEAD_RE = re.compile(r'\b(verse|verses|scripture|text|reading|meditation)\b', re.IGNORECASE)
REFLECT_HEAD_RE = re.compile(
    r'\b(thought|thoughts|reflection|reflections|devotional|lesson|lessons|meditation)\b',
    re.IGNORECASE,
)
PRAYER_HEAD_RE = re.compile(r'\b(prayer|prayers|prayer suggestion|suggested prayer)\b', re.IGNORECASE)

PRAYER_TERMINATOR = 'Pastor Alvin and Marcie Sather'


def find_all_headings(lines: List[str]) -> List[Tuple[int, str]]:
    heads = []
    for i, ln in enumerate(lines):
        m = HEADING_RE.match(ln)
        if not m:
            continue
        h = m.group('h').strip()
        # ignore obvious non-section labels
        if len(h) < 2:
            continue
        heads.append((i, h))
    return heads


def classify_heading(h: str) -> Optional[str]:
    if VERSE_HEAD_RE.search(h):
        return 'verse'
    if REFLECT_HEAD_RE.search(h):
        return 'reflection'
    if PRAYER_HEAD_RE.search(h):
        return 'prayer'
    return None


def find_semantic_positions(lines: List[str]) -> Dict[str, int]:
    """
    Find earliest verse-like, then earliest reflection-like after verse,
    then earliest prayer-like after reflection. Return dict of line indexes.
    """
    heads = find_all_headings(lines)
    pos = {}

    # find verse
    v_idx = None
    for i, h in heads:
        if classify_heading(h) == 'verse':
            v_idx = i
            pos['verse'] = i
            break
    if v_idx is None:
        return pos

    # find reflection after verse
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

    # find prayer after reflection
    for i, h in heads:
        if i <= r_idx:
            continue
        if classify_heading(h) == 'prayer':
            pos['prayer'] = i
            break

    return pos


def find_terminator_index(lines: List[str], terminator: str) -> Optional[int]:
    term = normalize(terminator).lower()
    for i, ln in enumerate(lines):
        if normalize(ln).lower() == term:
            return i
    return None


def slice_sections(lines: List[str], pos: Dict[str, int]) -> Dict[str, str]:
    verse = reflection = prayer = ''

    if 'verse' in pos:
        stop = pos.get('reflection', len(lines))
        verse = '\n'.join(lines[pos['verse'] + 1 : stop]).strip()

    if 'reflection' in pos:
        stop = pos.get('prayer', len(lines))
        reflection = '\n'.join(lines[pos['reflection'] + 1 : stop]).strip()

    if 'prayer' in pos:
        term_idx = find_terminator_index(lines, PRAYER_TERMINATOR)
        stop_candidates = [len(lines)]
        if term_idx is not None:
            stop_candidates.append(term_idx)
        stop = min(stop_candidates)
        prayer = '\n'.join(lines[pos['prayer'] + 1 : stop]).strip()

    return {'verse': verse, 'reflection': reflection, 'prayer': prayer}


def parse_one(full_text: str) -> Dict[str, Optional[str]]:
    hdr = extract_header_fields(full_text)
    body = extract_body(full_text)
    body_norm = normalize(body)
    lines = body_norm.splitlines()

    pos = find_semantic_positions(lines)
    sections = slice_sections(lines, pos)

    return {
        'message_id': hdr.get('message_id', ''),
        'date_utc': hdr.get('date', ''),
        'subject': hdr.get('subject', ''),
        'verse': sections['verse'] or '',
        'reflection': sections['reflection'] or '',
        'prayer': sections['prayer'] or '',
        'reading': '',
        'original_content': body_norm,
        'found_verse': 'verse' in pos,
        'found_reflection': 'reflection' in pos,
        'found_prayer': 'prayer' in pos,
    }


def main():
    files = sorted(INPUT_DIR.glob('*.txt'))
    if not files:
        print(f'No .txt files in {INPUT_DIR.resolve()}')
        return

    rows: List[Dict[str, str]] = []
    ids: List[str] = []

    total = len(files)
    found_any = found_all = 0

    for i, fp in enumerate(files, 1):
        txt = fp.read_text(encoding='utf-8', errors='replace')
        rec = parse_one(txt)

        any_ok = rec['found_verse'] or rec['found_reflection'] or rec['found_prayer']
        all_ok = rec['found_verse'] and rec['found_reflection'] and rec['found_prayer']

        if any_ok:
            found_any += 1
        if all_ok:
            found_all += 1
            if rec['message_id']:
                ids.append(rec['message_id'])

        # Only persist rows with all three sections; change here if you want to keep partials
        if all_ok:
            rows.append(
                {
                    'message_id': rec['message_id'],
                    'date_utc': rec['date_utc'],
                    'subject': rec['subject'],
                    'verse': rec['verse'],
                    'reflection': rec['reflection'],
                    'prayer': rec['prayer'],
                    'reading': rec['reading'],
                    'original_content': rec['original_content'],
                }
            )

        if i % 200 == 0 or i == total:
            print(f'Scanned {i}/{total} files...')

    print('\nSummary (semantic):')
    print(f'- Total files: {total}')
    print(f'- Files with any of the three: {found_any}')
    print(f'- Files with all three (usable): {found_all}')

    # Write outputs
    if ids:
        OUT_IDS.write_text('\n'.join(ids) + '\n', encoding='utf-8')
        print(f'Wrote IDs: {OUT_IDS.resolve()} ({len(ids)})')

    if rows:
        OUT_JSON.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'Wrote JSON: {OUT_JSON.resolve()} ({len(rows)})')

        with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    'message_id',
                    'date_utc',
                    'subject',
                    'verse',
                    'reflection',
                    'prayer',
                    'reading',
                    'original_content',
                ],
            )
            w.writeheader()
            w.writerows(rows)
        print(f'Wrote CSV: {OUT_CSV.resolve()} ({len(rows)})')


if __name__ == '__main__':
    main()
