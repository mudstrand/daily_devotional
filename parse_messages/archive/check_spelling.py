#!/usr/bin/env python3
import json
import os
import re
import sys
import shutil
import difflib
import unicodedata
from typing import Dict, List, Tuple, Optional

# Fields to process (override with --fields)
DEFAULT_FIELDS = ['subject', 'verse', 'reflection', 'prayer', 'reading']

# Built-in allowlists (extend via files)
GLOBAL_ALLOWLIST = {
    "else's",
    'uncircumcision',
    'lackest',
    'hearted',
    "another's",
    'flittering',
    'Israelites',
    'Christ-like',
    'Crispus',
    'Gaius',
    'Immanuel',
    'Triune',
    'Philippi',
    'Spurgeon',
    'Christhas',
    "disraeli's",
}
FIELD_ALLOWLIST: Dict[str, set] = {
    'reading': {'Ps'},
}
CUSTOM_WORDS = set()

# Optional allowlist files (one word per line, case-insensitive, '#' comments)
GLOBAL_ALLOWLIST_FILE = 'allowlist_global.txt'
FIELD_ALLOWLIST_FILE_TEMPLATE = 'allowlist_{field}.txt'

PAREN_RE = re.compile(r'\([^()]*\)')
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
SEPARATOR = '=' * 72

# Glue characters that may appear after a word
DASH_CHARS = r'\-–—‒―−‑'  # includes NB hyphen U+2011 (‑)
SOFT_HYPHEN = '\u00ad'
NBSP = '\u00a0'
NARROW_NBSP = '\u202f'
FIGURE_SPACE = '\u2007'
ZW_CHARS = '\u200c\u200d\u200b'  # ZWNJ, ZWJ, ZWSP
GLUE = f'{DASH_CHARS}{SOFT_HYPHEN}{NBSP}{NARROW_NBSP}{FIGURE_SPACE}{ZW_CHARS}'

# For normalization
DASH_MAP = {
    '\u2010': '-',  # hyphen
    '\u2011': '-',  # non-breaking hyphen
    '\u2012': '-',  # figure dash
    '\u2013': '-',  # en dash
    '\u2014': '-',  # em dash
    '\u2015': '-',  # horizontal bar
    '\u2212': '-',  # minus sign
}
ZERO_WIDTH = {'\u200b', '\u200c', '\u200d'}
SOFT_HYPHEN_CH = '\u00ad'


def read_json_file(path: str) -> Optional[Tuple[object, str]]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return json.loads(content), content
    except Exception:
        return None


def write_json_file(path: str, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text + '\n')


def load_allowlist_file(path: str) -> set:
    items = set()
    if not os.path.isfile(path):
        return items
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                items.add(s)
    except Exception:
        pass
    return items


def build_allowlists() -> Tuple[set, Dict[str, set], set]:
    global_words = set(GLOBAL_ALLOWLIST)
    field_map: Dict[str, set] = {k: set(v) for k, v in FIELD_ALLOWLIST.items()}
    global_words |= load_allowlist_file(GLOBAL_ALLOWLIST_FILE)
    for field in DEFAULT_FIELDS:
        fp = FIELD_ALLOWLIST_FILE_TEMPLATE.format(field=field)
        if os.path.isfile(fp):
            field_map.setdefault(field, set()).update(load_allowlist_file(fp))
    global_lower = {w.lower() for w in global_words}
    field_lower_map = {k: {w.lower() for w in v} for k, v in field_map.items()}
    custom_lower = {w.lower() for w in CUSTOM_WORDS}
    return global_lower, field_lower_map, custom_lower


def remove_parentheticals(text: str) -> str:
    prev = None
    curr = text
    while prev != curr:
        prev = curr
        curr = PAREN_RE.sub('', curr)
    return curr


def tokenize_words(text: str):
    return list(WORD_RE.finditer(text))


def preserve_case(original: str, suggestion: str) -> str:
    if original.islower():
        return suggestion.lower()
    if original.isupper():
        return suggestion.upper()
    if original.istitle():
        return suggestion.title()
    return suggestion


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


def is_allowed_word(
    word: str,
    field: str,
    global_allow: set,
    field_allow_map: Dict[str, set],
    custom_allow: set,
) -> bool:
    wl = word.lower()
    if wl in global_allow:
        return True
    if wl in field_allow_map.get(field, set()):
        return True
    if wl in custom_allow:
        return True
    return False


def suggestion_confidence(misspelled: str, suggestion: str) -> float:
    if not re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", suggestion):
        return 0.0
    base = difflib.SequenceMatcher(a=misspelled.lower(), b=suggestion.lower()).ratio()
    length_penalty = max(0.0, 1.0 - (abs(len(misspelled) - len(suggestion)) / max(1.0, len(misspelled))))
    conf = 0.75 * base + 0.25 * length_penalty
    return max(0.0, min(1.0, conf))


def best_suggestion(speller, misspelled: str, suggestions: List[str]) -> Optional[Tuple[str, float]]:
    candidates: List[Tuple[str, float]] = []
    miss_l = misspelled.lower()
    for s in suggestions:
        if not s:
            continue
        if not speller.check(s) or s.lower() == miss_l:
            continue
        candidates.append((s, suggestion_confidence(misspelled, s)))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0]


def normalize_for_match(s: str) -> str:
    s = unicodedata.normalize('NFKC', s)
    s = ''.join(ch for ch in s if ch not in ZERO_WIDTH and ch != SOFT_HYPHEN_CH)
    s = ''.join(DASH_MAP.get(ch, ch) for ch in s)
    return s


def normalize_text_for_fix(s: str) -> str:
    """
    Pre-clean common email hyphenation artifacts:
    - Remove soft hyphens and zero-width chars
    - Map all dash-like to hyphen
    - Remove hyphenation at line/space breaks: word-<spaces/newlines> -> word<space>
    - Remove final trailing hyphen at end of string: word- -> word
    """
    s0 = s
    s = unicodedata.normalize('NFKC', s)
    s = ''.join(ch for ch in s if ch not in ZERO_WIDTH and ch != SOFT_HYPHEN_CH)
    s = ''.join(DASH_MAP.get(ch, ch) for ch in s)
    # hyphenation at line/space breaks
    s = re.sub(r'([A-Za-z])-\s+', r'\1 ', s)
    # hyphen glued to punctuation-space (edge cases)
    s = re.sub(r'([A-Za-z])-\s*([,.;:!?])\s+', r'\1 \2 ', s)
    # trailing hyphen at end
    s = re.sub(r'([A-Za-z])-$', r'\1', s)
    return s if s != s0 else s0


def build_replacers(old: str, new: str):
    # Build normalized patterns (allow hyphen + optional whitespace as glue)
    old_norm = normalize_for_match(old)
    pat_glued_norm = re.compile(rf"\b{re.escape(old_norm)}(?:-+\s*('?|’)?)+\b")
    pat_bare_norm = re.compile(rf'\b{re.escape(old_norm)}\b')

    def repl_token_norm(m: re.Match) -> str:
        return preserve_case(m.group(0)[: len(old_norm)], new)

    # On original text, broad pattern: old followed by any GLUE or hyphen + whitespace, optional apostrophe
    glue_class = GLUE
    pat_orig = re.compile(rf"\b{re.escape(old)}(?:(?:[{glue_class}]+(?:'|’)?)+|-+\s+)?\b")

    def replace_on_original(original: str, replace_inside_parens: bool) -> Tuple[str, int]:
        def process_seg(seg: str) -> Tuple[str, int]:
            seg_norm = normalize_for_match(seg)
            seg2_norm, n1 = pat_glued_norm.subn(repl_token_norm, seg_norm)
            n = n1
            if n == 0:
                seg2_norm, n2 = pat_bare_norm.subn(repl_token_norm, seg_norm)
                n = n2
            if n == 0:
                return seg, 0
            # Replace up to n occurrences in the original using pat_orig
            replaced = 0

            def one_repl(mo: re.Match):
                nonlocal replaced
                if replaced >= n:
                    return mo.group(0)
                replaced += 1
                word_part = mo.group(0)[: len(old)]
                return preserve_case(word_part, new)

            out_seg = pat_orig.sub(one_repl, seg)
            return out_seg, replaced

        if replace_inside_parens:
            return process_seg(original)

        # Split original by parentheses and only process outside
        segments = []
        stack = []
        last = 0
        for i, ch in enumerate(original):
            if ch == '(':
                if not stack:
                    segments.append(('out', original[last:i]))
                    last = i
                stack.append(i)
            elif ch == ')':
                if stack:
                    stack.pop()
                    if not stack:
                        segments.append(('in', original[last : i + 1]))
                        last = i + 1
        segments.append(('out', original[last:]))

        out_parts = []
        total = 0
        for typ, seg in segments:
            if typ == 'out':
                seg2, n = process_seg(seg)
                out_parts.append(seg2)
                total += n
            else:
                out_parts.append(seg)
        return ''.join(out_parts), total

    def replace_everywhere(s: str) -> Tuple[str, int]:
        return replace_on_original(s, replace_inside_parens=True)

    def replace_outside_parens(s: str) -> Tuple[str, int]:
        return replace_on_original(s, replace_inside_parens=False)

    return replace_everywhere, replace_outside_parens


def find_field_key_line(content: str, key: str) -> int:
    for i, line in enumerate(content.splitlines(), start=1):
        if f'"{key}"' in line:
            return i
    return 1


def find_match_line_for_word(content: str, key: str, word: str) -> int:
    lines = content.splitlines(True)
    start_line_idx = next((i for i, ln in enumerate(lines) if f'"{key}"' in ln), 0)
    region = ''.join(lines[start_line_idx:])
    m = re.search(rf'\b{re.escape(word)}\b', region)
    if not m:
        return find_field_key_line(content, key)
    abs_index = sum(len(ln) for ln in lines[:start_line_idx]) + m.start()
    return content[:abs_index].count('\n') + 1


def collect_batch(
    speller,
    base_dir: str,
    fields: List[str],
    min_conf: float,
    lowercase_only: bool,
    page_size: int,
    global_allow: set,
    field_allow_map: Dict[str, set],
    custom_allow: set,
):
    """
    Return up to page_size items:
      dict: file, key, line, old, new, conf, apply_fn
    """
    batch = []
    for name in sorted(os.listdir(base_dir)):
        if not name.endswith('.json'):
            continue
        path = os.path.join(base_dir, name)
        loaded = read_json_file(path)
        if not loaded:
            continue
        data, content = loaded

        def per_field(obj: Dict, key: str):
            nonlocal batch
            val = obj.get(key)
            if not isinstance(val, str):
                return
            filtered = remove_parentheticals(val)
            for m in tokenize_words(filtered):
                if len(batch) >= page_size:
                    return
                w = m.group(0)
                # Skip tokens ending with an apostrophe to avoid possessive issues
                if w.endswith("'") or w.endswith('’'):
                    continue
                # Lowercase-first filter
                if lowercase_only and not w.islower():
                    continue
                if is_allowed_word(w, key, global_allow, field_allow_map, custom_allow):
                    continue
                if speller.check(w):
                    continue
                best = best_suggestion(speller, w, speller.suggest(w))
                if not best:
                    continue
                sug, conf = best
                if conf < min_conf:
                    continue
                fixed = preserve_case(w, sug)
                line = find_match_line_for_word(content, key, w)

                def make_apply(pth: str, field_key: str, old_word: str, new_word: str):
                    replace_everywhere, replace_outside_parens = build_replacers(old_word, new_word)

                    def apply_change(replace_inside_parens: bool, make_backup: bool = True):
                        loaded2 = read_json_file(pth)
                        if not loaded2:
                            return 0
                        data2, _content2 = loaded2
                        occurrences = 0
                        changed = False

                        def apply_to_obj(obj2: Dict):
                            nonlocal occurrences, changed
                            if field_key in obj2 and isinstance(obj2[field_key], str):
                                before = obj2[field_key]
                                # Pre-clean for line-wrap hyphenation artifacts
                                cleaned = normalize_text_for_fix(before)
                                source = cleaned
                                if cleaned != before:
                                    obj2[field_key] = cleaned
                                    occurrences += 1  # count as one cleanup occurrence
                                    changed = True
                                # Now run replacer on the possibly cleaned text
                                replacer = replace_everywhere if replace_inside_parens else replace_outside_parens
                                after, n = replacer(source)
                                if n > 0:
                                    obj2[field_key] = after
                                    occurrences += n
                                    changed = True

                        if isinstance(data2, list):
                            for it in data2:
                                if isinstance(it, dict):
                                    apply_to_obj(it)
                        elif isinstance(data2, dict):
                            apply_to_obj(data2)
                        if changed:
                            if make_backup:
                                shutil.copy2(pth, pth + '.bak')
                            write_json_file(pth, data2)
                        else:
                            print(
                                f"[debug] No change for {pth}:{field_key} '{old_word}' -> '{new_word}'",
                                file=sys.stderr,
                            )
                        return occurrences

                    return apply_change

                batch.append(
                    {
                        'file': name,
                        'key': key,
                        'line': line,
                        'old': w,
                        'new': fixed,
                        'conf': conf,
                        'apply_fn': make_apply(path, key, w, fixed),
                    }
                )

        # Process objects
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for f in fields:
                        per_field(item, f)
                        if len(batch) >= page_size:
                            break
                if len(batch) >= page_size:
                    break
        elif isinstance(data, dict):
            for f in fields:
                per_field(data, f)
                if len(batch) >= page_size:
                    break
        if len(batch) >= page_size:
            break
    return batch


def prompt_yes_no(question: str) -> str:
    while True:
        ans = input(f'{question} [y/n/q]: ').strip().lower()
        if ans in ('y', 'yes'):
            return 'y'
        if ans in ('n', 'no'):
            return 'n'
        if ans in ('q', 'quit'):
            return 'q'
        print('Please answer y, n, or q.')


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description='One-batch spelling suggestions across JSON fields; robust handling for hyphenation and invisible characters.'
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--count', action='store_true', help='List all matches (no changes)')
    mode.add_argument('--yes', action='store_true', help='Apply this batch without prompting')
    ap.add_argument(
        '--min-confidence',
        type=float,
        default=0.90,
        help='Minimum confidence (default 0.90)',
    )
    ap.add_argument('--fields', nargs='*', default=DEFAULT_FIELDS, help='Fields to scan')
    ap.add_argument('--page-size', type=int, default=20, help='Max suggestions in a batch')
    lf = ap.add_mutually_exclusive_group()
    lf.add_argument(
        '--lowercase-first',
        dest='lowercase_first',
        action='store_true',
        default=True,
        help='Only lowercase words (default)',
    )
    lf.add_argument(
        '--no-lowercase-first',
        dest='lowercase_first',
        action='store_false',
        help='Include capitalized words',
    )
    ap.add_argument(
        '--replace-inside-parens',
        action='store_true',
        help='Also replace inside parentheses',
    )
    args = ap.parse_args()

    if not (0.0 <= args.min_confidence <= 1.0):
        print('Error: --min-confidence must be between 0.0 and 1.0', file=sys.stderr)
        sys.exit(2)

    speller = init_speller()
    if not speller:
        print('Spelling checker not available; aborting.', file=sys.stderr)
        sys.exit(1)

    global_allow, field_allow_map, custom_allow = build_allowlists()

    # Count mode
    if args.count:
        total = 0
        for name in sorted(os.listdir(os.getcwd())):
            if not name.endswith('.json'):
                continue
            path = os.path.join(os.getcwd(), name)
            loaded = read_json_file(path)
            if not loaded:
                continue
            data, content = loaded

            def per_field_list(obj: Dict, key: str):
                nonlocal total
                val = obj.get(key)
                if not isinstance(val, str):
                    return
                filtered = remove_parentheticals(val)
                for m in tokenize_words(filtered):
                    w = m.group(0)
                    if args.lowercase_first and not w.islower():
                        continue
                    if w.endswith("'") or w.endswith('’'):
                        continue
                    if is_allowed_word(w, key, global_allow, field_allow_map, custom_allow):
                        continue
                    if speller.check(w):
                        continue
                    best = best_suggestion(speller, w, speller.suggest(w))
                    if not best:
                        continue
                    sug, conf = best
                    if conf < args.min_confidence:
                        continue
                    line = find_match_line_for_word(content, key, w)
                    print(
                        f"code -g {name}:{line} | {key}: '{w}' -> '{preserve_case(w, sug)}'  [confidence: {conf:.2f}]"
                    )
                    total += 1

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        for f in args.fields:
                            per_field_list(item, f)
            elif isinstance(data, dict):
                for f in args.fields:
                    per_field_list(data, f)
        print(SEPARATOR)
        print(f'Total suggestions: {total}')
        sys.exit(0)

    # Single-batch mode
    batch = collect_batch(
        speller=speller,
        base_dir=os.getcwd(),
        fields=args.fields,
        min_conf=args.min_confidence,
        lowercase_only=args.lowercase_first,
        page_size=args.page_size,
        global_allow=global_allow,
        field_allow_map=field_allow_map,
        custom_allow=custom_allow,
    )

    if not batch:
        print('No suggestions found.')
        sys.exit(0)

    print(SEPARATOR)
    for item in batch:
        print(
            f"code -g {item['file']}:{item['line']} | {item['key']}: '{item['old']}' -> '{item['new']}'  [confidence: {item['conf']:.2f}]"
        )
    print(SEPARATOR)

    if args.yes:
        decision = 'y'
    else:
        decision = prompt_yes_no('Apply ALL fixes in this batch?')

    if decision == 'q':
        print('Aborted.')
        sys.exit(1)
    if decision == 'n':
        print('Skipped applying this batch.')
        sys.exit(0)

    total_occurrences = 0
    for item in batch:
        total_occurrences += item['apply_fn'](replace_inside_parens=args.replace_inside_parens)

    print(f'Applied {total_occurrences} occurrence(s) across {len(batch)} suggestion(s).')


if __name__ == '__main__':
    main()
