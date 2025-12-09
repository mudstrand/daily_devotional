#!/usr/bin/env python3
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

# Fields to check
FIELDS = ['subject', 'verse', 'reflection', 'prayer', 'reading']

# Config
LANG_CODE = 'en-US'
USE_GRAMMAR = True
USE_SPELL = True  # now enabled

# Optional domain words to ignore for spelling
CUSTOM_WORDS = {
    # Add proper nouns or domain-specific terms here to reduce false positives.
    # "Eucharist", "Thessalonians", "Lectio", "Ignatian",
}

# Globals for tools
lt = None
speller = None


def init_tools():
    global lt, speller
    # Grammar tool
    if USE_GRAMMAR:
        try:
            import language_tool_python as lt_mod

            try:
                # Try local serverless (downloads LT once). Comment this and uncomment PublicAPI to avoid the download.
                lt = lt_mod.LanguageTool(LANG_CODE)
            except Exception:
                # Fallback to public API (rate-limited, internet required)
                lt = lt_mod.LanguageToolPublicAPI(LANG_CODE)
        except Exception as e:
            print(
                f'Warning: language_tool_python unavailable ({e}); grammar checks disabled.',
                file=sys.stderr,
            )
            lt = None

    # Spelling tool
    if USE_SPELL:
        try:
            import enchant as enchant_mod

            try:
                speller = enchant_mod.Dict('en_US')
            except enchant_mod.errors.DictNotFoundError:
                # Try en_US-large if available
                try:
                    speller = enchant_mod.Dict('en_US-large')
                except Exception:
                    print(
                        'Warning: pyenchant en_US dictionary not found; spell checks disabled.',
                        file=sys.stderr,
                    )
                    speller = None
        except Exception as e:
            print(
                f'Warning: pyenchant unavailable ({e}); spell checks disabled.',
                file=sys.stderr,
            )
            speller = None


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def read_json_file(path: str) -> Optional[Tuple[object, str]]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return json.loads(content), content
    except Exception:
        return None


def find_line_number_for_field(content: str, key: str, value: str) -> int:
    """
    Find the 1-based line number where "<key>": "<value>" appears.
    Try exact JSON snippet first, then a looser match.
    """
    escaped_key = re.escape(key)
    # Escape value for regex, but handle embedded quotes safely
    escaped_val = re.escape(value)
    pattern = re.compile(
        r'^\s*"' + escaped_key + r'"\s*:\s*"' + escaped_val + r'"\s*(?:,|}|])',
        re.MULTILINE,
    )
    m = pattern.search(content)
    if m:
        return content.count('\n', 0, m.start()) + 1

    exact = f'"{key}": "{value}"'
    for i, line in enumerate(content.splitlines(), start=1):
        if exact in line:
            return i

    # Fallback: line containing the key and a fragment of the value
    frag = value[:30] if isinstance(value, str) else ''
    if frag:
        for i, line in enumerate(content.splitlines(), start=1):
            if f'"{key}"' in line and frag in line:
                return i
    return -1


def check_spelling(text: str) -> List[Tuple[str, int]]:
    """
    Return list of (word, position) for suspected misspellings.
    Uses a simple tokenizer; ignores words in CUSTOM_WORDS, small acronyms.
    """
    if not speller:
        return []
    issues = []
    custom_lower = {w.lower() for w in CUSTOM_WORDS}
    for m in re.finditer(r"[A-Za-z][A-Za-z'\-]*", text):
        w = m.group(0)
        wl = w.lower()
        if wl in custom_lower:
            continue
        # Skip all-caps acronyms up to length 5
        if w.isupper() and len(w) <= 5:
            continue
        # Skip single-letter words except a, I
        if len(w) == 1 and wl not in ('a', 'i'):
            continue
        if not speller.check(w):
            issues.append((w, m.start()))
    return issues


def lt_matches(text: str):
    if not lt:
        return []
    try:
        return lt.check(text)
    except Exception:
        return []


def match_span(m) -> Tuple[int, int]:
    """
    Return (offset, length) for a LanguageTool match, robust across versions.
    """
    offset = getattr(m, 'offset', None)
    length = getattr(m, 'errorLength', None)

    if offset is None:
        offset = getattr(m, 'offsetInContext', 0)
    if length is None:
        # If exact length missing, attempt to derive from 'context' field
        try:
            ctx = getattr(m, 'context', None) or getattr(m, 'contextForSureMatch', None)
            length = len(str(ctx)) if ctx else 0
        except Exception:
            length = 0

    try:
        offset = int(offset)
    except Exception:
        offset = 0
    try:
        length = int(length)
    except Exception:
        length = 0
    return offset, length


def match_message(m) -> str:
    rid = getattr(m, 'ruleId', None) or getattr(m, 'rule', None) or 'RULE'
    msg = getattr(m, 'message', None) or 'Issue'
    # Prefer concise output
    return f'Grammar ({rid}): {msg}'


def report_issue(field: str, msg: str, filename: str, line: int):
    line = 1 if line == -1 else line
    print(f'{field}: {msg} -> code -g {filename}:{line}')


def inspect_record(obj: Dict, file_content: str, filename: str):
    for field in FIELDS:
        val = obj.get(field)
        if not isinstance(val, str):
            continue
        text = val

        # Spelling
        for word, pos in check_spelling(text):
            msg = f"Spelling? '{word}'"
            line = find_line_number_for_field(file_content, field, text)
            report_issue(field, msg, filename, line)

        # Grammar/style
        for m in lt_matches(text):
            offset, length = match_span(m)
            start = max(0, offset - 20)
            end = min(len(text), offset + max(1, length) + 20)
            context = text[start:end].replace('\n', ' ')
            msg = f'{match_message(m)} | ...{context}...'
            line = find_line_number_for_field(file_content, field, text)
            report_issue(field, msg, filename, line)


def main():
    init_tools()
    base = script_dir()

    try:
        entries = os.listdir(base)
    except FileNotFoundError:
        print('Cannot list script directory', file=sys.stderr)
        sys.exit(1)

    any_json = False
    for name in sorted(entries):
        if not name.endswith('.json'):
            continue
        path = os.path.join(base, name)
        loaded = read_json_file(path)
        if not loaded:
            continue
        any_json = True
        data, content = loaded

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    inspect_record(item, content, name)
        elif isinstance(data, dict):
            inspect_record(data, content, name)

    if not any_json:
        print('No JSON files found', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
