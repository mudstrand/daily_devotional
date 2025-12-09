#!/usr/bin/env python3
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

INPUT_DIR = Path('missing')
PROFILE_FILE = Path('generated_profile.json')
OUT_JSON = Path('parsed_profile.json')
OUT_IDS = Path('handled_profile.ids')

HDR_BODY_SEP = '=' * 67
BODY_HEADER_RE = re.compile(
    rf'^{re.escape(HDR_BODY_SEP)}\s*Body \(clean, unformatted\):\s*{re.escape(HDR_BODY_SEP)}\s*',
    re.MULTILINE,
)


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


def slice_section(
    lines: List[str],
    start_idx: int,
    inline_first: str,
    next_idx: Optional[int],
    term_res: List[re.Pattern],
    is_prayer: bool,
) -> str:
    stop = next_idx if next_idx is not None else len(lines)
    if is_prayer and term_res:
        for i in range(start_idx + 1, stop):
            if any(tr.search(lines[i]) for tr in term_res):
                stop = i
                break
    parts = []
    if inline_first:
        parts.append(inline_first)
    if start_idx + 1 < stop:
        parts.append('\n'.join(lines[start_idx + 1 : stop]).strip())
    return '\n'.join([p for p in parts if p]).strip()


def main():
    import argparse

    ap = argparse.ArgumentParser(description='Parse messages using a generated profile (JSON-only outputs)')
    ap.add_argument('--profile', default=str(PROFILE_FILE), help='Path to generated_profile.json')
    ap.add_argument('--input-dir', default=str(INPUT_DIR), help='Directory with saved .txt messages')
    args = ap.parse_args()

    profile = json.loads(Path(args.profile).read_text(encoding='utf-8'))
    verse_rx = re.compile(profile['verse_pattern'], re.I | re.M)
    refl_rx = re.compile(profile['reflection_pattern'], re.I | re.M)
    pray_rx = re.compile(profile['prayer_pattern'], re.I | re.M)
    term_res = [re.compile(t, re.I) for t in profile.get('terminators', [])]

    files = sorted(Path(args.input_dir).glob('*.txt'))

    rows: List[Dict[str, str]] = []
    handled_ids: List[str] = []
    matched = 0

    total = len(files)
    for i, fp in enumerate(files, 1):
        txt = fp.read_text(encoding='utf-8', errors='replace')
        hdr = extract_header_fields(txt)
        body = extract_body(txt)
        lines = normalize(body).splitlines()

        def find_idx_inline(rx: re.Pattern) -> Tuple[Optional[int], str]:
            for idx, ln in enumerate(lines):
                m = rx.match(ln)
                if m:
                    return idx, (m.group('inline') or '').strip()
            return None, ''

        v_idx, v_inline = find_idx_inline(verse_rx)
        r_idx, r_inline = find_idx_inline(refl_rx)
        p_idx, p_inline = find_idx_inline(pray_rx)

        ok = v_idx is not None and r_idx is not None and p_idx is not None and (v_idx < r_idx < p_idx)
        if ok:
            verse = slice_section(lines, v_idx, v_inline, r_idx, term_res, False)
            reflection = slice_section(lines, r_idx, r_inline, p_idx, term_res, False)
            prayer = slice_section(lines, p_idx, p_inline, None, term_res, True)

            rows.append(
                {
                    'message_id': hdr.get('message_id', fp.stem),
                    'date_utc': hdr.get('date', ''),
                    'subject': hdr.get('subject', ''),
                    'verse': verse,
                    'reflection': reflection,
                    'prayer': prayer,
                    'reading': '',
                    'original_content': '\n'.join(lines),
                }
            )
            handled_ids.append(hdr.get('message_id', fp.stem))
            matched += 1

        if i % 200 == 0 or i == total:
            print(f'Processed {i}/{total} files...')

    print(f'\nMatched with profile: {matched}/{total}')

    OUT_JSON.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
    OUT_IDS.write_text('\n'.join(handled_ids) + ('\n' if handled_ids else ''), encoding='utf-8')
    print(f'Wrote parsed JSON: {OUT_JSON.resolve()} ({len(rows)} records)')
    print(f'Wrote handled IDs: {OUT_IDS.resolve()} ({len(handled_ids)} ids)')


if __name__ == '__main__':
    main()
