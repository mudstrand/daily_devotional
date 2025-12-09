#!/usr/bin/env python3
import argparse
import re
from pathlib import Path
from typing import List, Set, Tuple

BOOK = r'(?:[1-3]\s+)?[A-Za-z][A-Za-z ]+'
CH = r'\d+'
VER = r'\d+(?:[abc])?'  # allow a/b/c suffixes but we’ll ignore suffixes when counting
RANGE = rf'{VER}(?:\s*-\s*{VER})?'
LIST = rf'{RANGE}(?:\s*,\s*{RANGE})*'
REF_RE = re.compile(rf'^\s*({BOOK})\s+({CH})\s*:\s*({LIST})\s*$', re.IGNORECASE)
WHOLE_CH_RE = re.compile(rf'^\s*({BOOK})\s+({CH})\s*$', re.IGNORECASE)


def strip_abc(s: str) -> str:
    return re.sub(r'(\d)\s*[abc]\b', r'\1', s, flags=re.IGNORECASE)


def parse_line(line: str) -> Tuple[str, int, str]:
    """
    Returns (book, chapter, verse_list) for a normalized line.
    Raises ValueError if unparsable.
    """
    s = line.strip()
    s = re.sub(r'\s*:\s*', ':', s)
    s = re.sub(r'\s*,\s*', ',', s)
    s = re.sub(r'\s*-\s*', '-', s)
    s = re.sub(r'\s{2,}', ' ', s)

    m = REF_RE.match(strip_abc(s))
    if m:
        return (' '.join(m.group(1).split()), int(m.group(2)), m.group(3))
    mch = WHOLE_CH_RE.match(s)
    if mch:
        # Whole-chapter request present (e.g., "Psalm 23") – you have several lines like "Psalm 23:4", but
        # your list also includes a few "Psalm 23" whole-chapter lines. We cannot know the last verse
        # without a versification table; for counting, mark as unknown.
        raise ValueError(f'Whole-chapter without verse range: {line!r}')
    raise ValueError(f'Unparsable reference: {line!r}')


def expand_verses(verse_list: str) -> List[int]:
    out: List[int] = []
    for seg in verse_list.split(','):
        seg = seg.strip()
        if not seg:
            continue
        if '-' in seg:
            a, b = seg.split('-', 1)
            a_num = int(re.sub(r'[^\d]', '', a))
            b_num = int(re.sub(r'[^\d]', '', b))
            if b_num < a_num:
                a_num, b_num = b_num, a_num
            out.extend(range(a_num, b_num + 1))
        else:
            out.append(int(re.sub(r'[^\d]', '', seg)))
    return out


def main():
    ap = argparse.ArgumentParser(description='Count total and unique verses requested by a reference list.')
    ap.add_argument('file', help='Text file with one reference per line')
    ap.add_argument(
        '--dedupe',
        action='store_true',
        help='Also compute unique verse triples (book,chapter,verse)',
    )
    args = ap.parse_args()

    lines = [ln.strip() for ln in Path(args.file).read_text(encoding='utf-8').splitlines() if ln.strip()]
    total = 0
    uniques: Set[Tuple[str, int, int]] = set()
    whole_chapter_refs: List[str] = []

    for ln in lines:
        try:
            book, ch, vlist = parse_line(ln)
        except ValueError as e:
            # if it's a whole chapter (e.g., "Psalm 23"), collect to report
            if 'Whole-chapter' in str(e):
                whole_chapter_refs.append(ln)
                continue
            # otherwise warn and skip
            print(f'[WARN] {e}')
            continue

        verses = expand_verses(vlist)
        total += len(verses)
        if args.dedupe:
            for v in verses:
                uniques.add((book, ch, v))

    print(f'Total verse requests (raw sum across lines): {total}')
    if args.dedupe:
        print(f'Unique verses (book,chapter,verse triples): {len(uniques)}')

    if whole_chapter_refs:
        print('\nWhole-chapter references (unknown verse count unless expanded):')
        for r in whole_chapter_refs:
            print(f'  - {r}')


if __name__ == '__main__':
    main()
