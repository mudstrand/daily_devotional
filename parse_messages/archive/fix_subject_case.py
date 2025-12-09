#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SEPARATOR = '=' * 50

# Small/common words typically lowercase in Title Case
SMALL_WORDS = {
    'a',
    'an',
    'and',
    'as',
    'at',
    'but',
    'by',
    'for',
    'in',
    'nor',
    'of',
    'on',
    'or',
    'per',
    'the',
    'to',
    'vs',
    'via',
    'is',
    'be',
    'am',
    'are',
    'was',
    'were',
    'from',
    'with',
    'into',
    'over',
    'under',
    'than',
    'then',
    'so',
    'yet',
}

# Acronyms/initialisms to preserve in ALL CAPS
ACRONYM_KEEP = {
    'AI',
    'ESV',
    'NIV',
    'KJV',
    'NKJV',
    'NASB',
    'NASB95',
    'NLT',
    'CSB',
    'NRSV',
    'RSV',
    'ASV',
}

# Proper devotional terms to prefer exact casing after title-casing
PROPER_OVERRIDES = {
    'god': 'God',
    'jesus': 'Jesus',
    'christ': 'Christ',
    'holy': 'Holy',  # e.g., Holy Spirit
    'spirit': 'Spirit',  # e.g., Holy Spirit
    'bible': 'Bible',
    'scripture': 'Scripture',
    'scriptures': 'Scriptures',
    'gospel': 'Gospel',
    'lord': 'Lord',
    'savior': 'Savior',
    'kingdom': 'Kingdom',
}

# Common direct typo fixes before calling spell checker
DIRECT_FIXES = {
    'yor': 'your',
    'recieve': 'receive',
    'beleive': 'believe',
    'teh': 'the',
    'widsom': 'wisdom',
    'heavan': 'heaven',
    'heavanly': 'heavenly',
    'provervs': 'proverbs',
}

# Regex helpers
WORD_SPLIT_RE = re.compile(r'[ \t]+')
MULTISPACE_RE = re.compile(r'\s{2,}')
LEADING_TRAIL_NONALNUM_RE = re.compile(r'^[^\w]+|[^\w]+$')
TRAIL_PUNCT_RE = re.compile(r'([!?\.]+)\s*$')


def init_speller():
    try:
        import enchant as enchant_mod

        try:
            return enchant_mod.Dict('en_US')
        except enchant_mod.errors.DictNotFoundError:
            try:
                return enchant_mod.Dict('en_US-large')
            except Exception:
                print('Error: pyenchant en_US dictionary not found.', file=sys.stderr)
                return None
    except Exception as e:
        print(f'Error: pyenchant unavailable ({e}).', file=sys.stderr)
        return None


def split_words(title: str) -> List[str]:
    s = MULTISPACE_RE.sub(' ', title.strip())
    if not s:
        return []
    return [w for w in WORD_SPLIT_RE.split(s) if w]


def is_small(w: str) -> bool:
    return w.lower() in SMALL_WORDS


def should_preserve_acronym(token: str) -> bool:
    core = re.sub(r'[^\w]', '', token)
    return core in ACRONYM_KEEP


def apply_proper_overrides(word: str) -> str:
    lw = word.lower()
    return PROPER_OVERRIDES.get(lw, word)


def smart_title_case(words: List[str]) -> List[str]:
    if not words:
        return words
    out: List[str] = []
    n = len(words)
    for i, w in enumerate(words):
        core = w.strip()
        if not core:
            out.append(core)
            continue

        # Preserve configured acronyms
        if should_preserve_acronym(core):
            out.append(core.upper())
            continue

        lw = core.lower()
        # Lowercase if small and not first/last
        if i != 0 and i != n - 1 and lw in SMALL_WORDS:
            out.append(lw)
            continue

        # Title-case, including hyphenated parts
        if '-' in core:
            parts = core.split('-')
            tc_parts = []
            for p in parts:
                if not p:
                    tc_parts.append(p)
                elif should_preserve_acronym(p):
                    tc_parts.append(p.upper())
                else:
                    tc_parts.append(p[:1].upper() + p[1:].lower())
            out.append('-'.join(tc_parts))
        else:
            out.append(core[:1].upper() + core[1:].lower())
    return out


def clean_token_keep_punct(token: str) -> Tuple[str, str]:
    """
    Separate core token from trailing punctuation, e.g., "wallet?" -> ("wallet", "?")
    Preserve apostrophes (God's) and curly apostrophes (’).
    """
    m = re.match(r"^([A-Za-z0-9'’-]+)([^A-Za-z0-9'’-]*)$", token)
    if not m:
        return token, ''
    return m.group(1), m.group(2)


def enchant_correct_word(speller, token: str) -> str:
    """
    Correct a single token using pyenchant Dict.
    Conservatively skip:
      - Acronyms in ACRONYM_KEEP
      - Tokens with digits or underscores
      - Very short tokens (<= 2)
    Handle hyphens and apostrophes (possessives) carefully.
    """
    if not token:
        return token
    # Skip digits/underscores
    if re.search(r'\d|_', token):
        return token
    # Preserve configured acronyms
    if should_preserve_acronym(token):
        return token.upper()
    # Short tokens: keep (we’ll title-case later as needed)
    if len(token) <= 2:
        return token

    # Direct, known fixes
    if token.lower() in DIRECT_FIXES:
        return DIRECT_FIXES[token.lower()]

    # Hyphenated words: correct parts independently
    if '-' in token:
        parts = token.split('-')
        corr_parts = [enchant_correct_word(speller, p) for p in parts]
        return '-'.join(corr_parts)

    # Apostrophes/possessives: correct stem; leave suffix as-is if it's a typical contraction/possessive
    if "'" in token or '’' in token:
        apos = "'" if "'" in token else '’'
        stem, rest = token.split(apos, 1)
        stem_corr = enchant_correct_word(speller, stem)
        if rest.lower() in ('s', 'd', 'll', 're', 've', 'm', 't'):
            return stem_corr + apos + rest
        else:
            # Keep arbitrary tail as-is; we don't want to over-correct
            return stem_corr + apos + rest

    # Now plain word: ask speller
    lw = token.lower()
    try:
        if speller and not speller.check(lw):
            # If unknown, try suggestions
            sugg = speller.suggest(lw)
            if sugg:
                # Choose first suggestion that is alphabetic and simple
                for cand in sugg:
                    if re.match(r'^[A-Za-z]+$', cand):
                        return cand.lower()  # return lowercase; title-casing comes later
            # No good suggestion; keep original
            return token
        else:
            return token
    except Exception:
        # If speller throws, keep original token
        return token


def title_case_and_spellcheck(subject: str, speller) -> str:
    # Preserve trailing punctuation (. ? !)
    trailing = ''
    m = TRAIL_PUNCT_RE.search(subject)
    if m:
        trailing = m.group(1)
        s_work = subject[: m.start()].rstrip()
    else:
        s_work = subject.strip()

    # Clean edges and collapse spaces
    s_work = LEADING_TRAIL_NONALNUM_RE.sub('', s_work)
    s_work = MULTISPACE_RE.sub(' ', s_work)

    words_raw = split_words(s_work)
    if not words_raw:
        return subject.strip()

    # Spell-check each token (preserving token-level punctuation if any)
    corrected: List[str] = []
    for tok in words_raw:
        core, punct = clean_token_keep_punct(tok)
        corrected_core = enchant_correct_word(speller, core)
        corrected.append(corrected_core + punct)

    # Title-case
    tc_words = smart_title_case(corrected)

    # Apply devotional proper-noun overrides
    final_words = [apply_proper_overrides(w) for w in tc_words]

    out = ' '.join(final_words).strip()
    if trailing:
        out = f'{out}{trailing}'
    return out


def normalize_subject_case_and_spelling(s: str, speller) -> str:
    if not isinstance(s, str):
        return s
    return title_case_and_spellcheck(s, speller)


def load_json_records(data: Any, filename: Path):
    if isinstance(data, list):
        return data, None, None
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            return data[list_keys[0]], data, list_keys[0]
        raise ValueError(f'{filename}: expected a list or a dict with a single list of records')
    raise ValueError(f'{filename}: unsupported JSON structure')


def process_file(path: Path, preview: bool) -> int:
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        records, container, key = load_json_records(raw, path)
    except Exception as e:
        print(f'[ERROR] {path}: cannot read/parse JSON: {e}')
        return 2

    speller = init_speller()

    updated_records: List[Dict[str, Any]] = []
    preview_items: List[Tuple[int, Dict[str, str]]] = []

    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            updated_records.append(rec)
            continue

        subj = rec.get('subject')
        if not isinstance(subj, str) or not subj.strip():
            updated_records.append(rec)
            continue

        new_subj = normalize_subject_case_and_spelling(subj, speller)
        if new_subj and new_subj != subj:
            rec_copy = dict(rec)
            rec_copy['subject'] = new_subj
            updated_records.append(rec_copy)
            if preview:
                preview_items.append((idx, {'before': subj, 'after': new_subj}))
        else:
            updated_records.append(rec)

    if preview:
        if preview_items:
            print(f'\n=== Preview: {path} ===')
            for idx, payload in preview_items:
                print(SEPARATOR)
                print(f'Record {idx}:')
                print(f'- subject (before): {payload["before"]}')
                print(f'- subject (after) : {payload["after"]}')
            print(SEPARATOR)
        return 0

    try:
        if container is None:
            out = updated_records
        else:
            container[key] = updated_records
            out = container
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'[OK] {path}: updated')
        return 0
    except Exception as e:
        print(f'[ERROR] {path}: failed to write output: {e}')
        return 2


def main():
    parser = argparse.ArgumentParser(
        description='Fix subject casing to Title Case and spell-check with pyenchant (no shortening).'
    )
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    parser.add_argument('--preview', action='store_true', help='Show changes without writing files')
    args = parser.parse_args()

    exit_code = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] {path}: not found')
            exit_code = max(exit_code, 2)
            continue
        rc = process_file(path, preview=args.preview)
        exit_code = max(exit_code, rc)

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
