i  #!/usr/bin/env python3
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Defaults
CORPUS_FILE = Path('corpus_samples.txt')
PROFILE_OUT = Path('generated_profile.json')
PREVIEW_JSON = Path('corpus_preview.json')

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


def split_corpus_into_messages(text: str) -> List[str]:
    parts = re.split(r'(?=^message_id:\s)', text, flags=re.MULTILINE)
    msgs = [p.strip() for p in parts if p.strip()]
    if len(msgs) <= 1:
        parts = re.split(rf'(?m)^{re.escape(HDR_BODY_SEP)}\s*$', text)
        rebuilt = []
        acc = []
        for p in parts:
            if p.strip():
                acc.append(p)
                if len(acc) >= 3:
                    rebuilt.append(HDR_BODY_SEP.join(acc[-3:]))
                    acc = []
        if not rebuilt:
            rebuilt = [text]
        msgs = [m.strip() for m in rebuilt if m.strip()]
    return msgs


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


def compile_heading_regex(keywords: List[str]) -> re.Pattern:
    kw_alt = '|'.join(re.escape(k) for k in keywords if k.strip())
    APO = r"[’'`´]?"
    pat = rf'^\s*(?:Today{APO}s?\s+|Our\s+)?(?:{kw_alt})(?:\s+for\s+Today)?\s*:\s*(?P<inline>.*)$'
    return re.compile(pat, re.IGNORECASE | re.MULTILINE)


def find_line_index_and_inline(lines: List[str], rx: re.Pattern) -> Tuple[Optional[int], str]:
    for idx, ln in enumerate(lines):
        m = rx.match(ln)
        if m:
            return idx, (m.group('inline') or '').strip()
    return None, ''


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

    ap = argparse.ArgumentParser(description='Build a parsing profile from a corpus file (JSON-only outputs)')
    ap.add_argument(
        '--corpus',
        default=str(CORPUS_FILE),
        help='Path to corpus file with sample messages',
    )
    ap.add_argument('--verse', nargs='+', required=True, help='Loose keywords for verse headings')
    ap.add_argument(
        '--reflect',
        nargs='+',
        required=True,
        help='Loose keywords for reflection headings',
    )
    ap.add_argument('--prayer', nargs='+', required=True, help='Loose keywords for prayer headings')
    ap.add_argument(
        '--terminator',
        nargs='*',
        default=['Pastor Alvin and Marcie Sather'],
        help='Optional terminator lines for prayer',
    )
    args = ap.parse_args()

    txt = Path(args.corpus).read_text(encoding='utf-8', errors='replace')
    messages = split_corpus_into_messages(txt)
    print(f'Loaded {len(messages)} messages from corpus.')

    verse_rx = compile_heading_regex(args.verse)
    refl_rx = compile_heading_regex(args.reflect)
    pray_rx = compile_heading_regex(args.prayer)
    term_res = [re.compile(t, re.I) for t in args.terminator or []]

    preview = []
    matched = 0

    for msg in messages:
        hdr = extract_header_fields(msg)
        body = extract_body(msg)
        lines = normalize(body).splitlines()

        v_idx, v_inline = find_line_index_and_inline(lines, verse_rx)
        r_idx, r_inline = find_line_index_and_inline(lines, refl_rx)
        p_idx, p_inline = find_line_index_and_inline(lines, pray_rx)

        ok = v_idx is not None and r_idx is not None and p_idx is not None and (v_idx < r_idx < p_idx)
        if ok:
            matched += 1
            verse = slice_section(lines, v_idx, v_inline, r_idx, term_res, False)
            refl = slice_section(lines, r_idx, r_inline, p_idx, term_res, False)
            pray = slice_section(lines, p_idx, p_inline, None, term_res, True)
            preview.append(
                {
                    'message_id': hdr.get('message_id', ''),
                    'date_utc': hdr.get('date', ''),
                    'subject': hdr.get('subject', ''),
                    'verse': verse,
                    'reflection': refl,
                    'prayer': pray,
                    'original_content': '\n'.join(lines),
                }
            )

    profile = {
        'name': 'generated_profile',
        'verse_pattern': verse_rx.pattern,
        'reflection_pattern': refl_rx.pattern,
        'prayer_pattern': pray_rx.pattern,
        'terminators': args.terminator or [],
    }
    PROFILE_OUT.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding='utf-8')
    PREVIEW_JSON.write_text(json.dumps(preview, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote profile: {PROFILE_OUT.resolve()}')
    print(f'Wrote preview JSON: {PREVIEW_JSON.resolve()} (matched {matched}/{len(messages)})')


if __name__ == '__main__':
    main()
