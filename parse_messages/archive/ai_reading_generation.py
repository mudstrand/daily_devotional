#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from anthropic import Anthropic, APIStatusError  # pip install anthropic

SEPARATOR = '=' * 50

# Defaults (tune as needed)
DEFAULT_MODEL = os.getenv('CLAUDE_READING_MODEL', 'claude-3-haiku-20240307')
DEFAULT_MAX_TOKENS = int(os.getenv('CLAUDE_READING_MAX_TOKENS', '200'))
DEFAULT_TEMPERATURE = float(os.getenv('CLAUDE_READING_TEMPERATURE', '0.3'))
DEFAULT_RETRIES = int(os.getenv('CLAUDE_READING_RETRIES', '3'))
DEFAULT_RETRY_DELAY = float(os.getenv('CLAUDE_READING_RETRY_DELAY', '1.5'))

# Acceptable Bible reference pattern (simple, tolerant), e.g.:
# "Romans 5:1-2", "1 Corinthians 2:9", "John 3:16-18", "Proverbs 3:5,6"
# We’ll normalize later to tighten spaces.
BOOK = r'(?:[1-3]\s+)?[A-Za-z][A-Za-z ]+'
CH = r'\d+'
VER = r'\d+(?:[abc])?'
RANGE = rf'{VER}(?:\s*-\s*{VER})?'
LIST = rf'{RANGE}(?:\s*,\s*{RANGE})*'
REF_REGEX = re.compile(rf'^\s*({BOOK})\s+({CH})\s*:\s*({LIST})\s*$', re.IGNORECASE)


def normalize_reference(ref: str) -> str:
    """
    Normalize reference to canonical spacing:
      'Book  C:V1- V2 , V3- V4' -> 'Book C:V1-V2,V3-V4'
    Also strip a/b/c suffixes in the comparison phase only; we return the original format.
    """
    s = ref.strip()
    # Collapse spaces around colon and commas/hyphens
    s = re.sub(r'\s*:\s*', ':', s)
    s = re.sub(r'\s*,\s*', ',', s)
    s = re.sub(r'\s*-\s*', '-', s)
    # Collapse multi spaces
    s = re.sub(r'\s{2,}', ' ', s)
    return s


def strip_abc_suffixes(ref: str) -> str:
    """
    For comparison only: remove partial-verse suffixes a/b/c from verse numbers.
    """
    return re.sub(r'(\d)\s*[abc]\b', r'\1', ref, flags=re.IGNORECASE)


def parse_reference(ref: str) -> Optional[Tuple[str, str, str]]:
    """
    Return (book, chapter, verses) if it looks like a valid reference per our regex, else None.
    """
    s = normalize_reference(ref)
    m = REF_REGEX.match(s)
    if not m:
        return None
    return (m.group(1), m.group(2), m.group(3))


def same_reference(ref1: str, ref2: str) -> bool:
    """
    Compare two references ignoring minor spacing and a/b/c suffixes.
    """
    n1 = strip_abc_suffixes(normalize_reference(ref1)).lower()
    n2 = strip_abc_suffixes(normalize_reference(ref2)).lower()
    return n1 == n2


def count_verses(verses: str) -> int:
    """
    Count how many individual verses are included in a verse list string like:
      '1-3,5,7-8' => 1..3 (3) + 5 (1) + 7..8 (2) = 6
    """
    total = 0
    for segment in verses.split(','):
        seg = segment.strip()
        if '-' in seg:
            a, b = seg.split('-', 1)
            try:
                start = int(re.sub(r'[^\d]', '', a))
                end = int(re.sub(r'[^\d]', '', b))
                if end >= start:
                    total += end - start + 1
                else:
                    total += 1  # fallback count if malformed
            except Exception:
                total += 1
        else:
            total += 1
    return total


def build_claude_messages(reflection: str, current_verse: str) -> List[Dict[str, str]]:
    """
    Prompt Claude to suggest 1–4 verses (fewest needed) that relate to the reflection
    and are different from the current 'verse' field.
    """
    reflection = (reflection or '').strip()
    current_verse = (current_verse or '').strip()

    instr = (
        'You suggest a concise Bible reading reference (1–4 verses total, the fewest needed) that closely relates '
        'to the reflection. The reading must be different from the verse already used for the subject. '
        'Return ONLY the reference in the form:\n'
        'Book Chapter:Verses\n'
        'Examples: Romans 5:1-2, John 3:16, Proverbs 3:5-6, 1 Corinthians 2:9\n\n'
        'Constraints:\n'
        '- 1 to 4 total verses preferred (fewest possible)\n'
        '- Must not equal the existing verse below\n'
        '- Do not include quotes, punctuation beyond standard format, or extra text\n'
    )
    context = f'Existing verse (must avoid): {current_verse}\nReflection:\n{reflection}\n'
    return [{'role': 'user', 'content': f'{instr}\n{context}Return one reference only.'}]


def call_claude_for_reading(
    client: Anthropic,
    reflection: str,
    current_verse: str,
    model: str,
    max_tokens: int,
    temperature: float,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> str:
    """
    Ask Claude for a reading reference. Validate format, ensure different than current_verse, and <= 4 verses.
    """
    messages = build_claude_messages(reflection, current_verse)
    last_err: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
            )
            # Anthropic content blocks
            text_parts: List[str] = []
            for block in resp.content or []:
                if getattr(block, 'type', None) == 'text':
                    text_parts.append(block.text)
                elif isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
            raw = ' '.join([p for p in text_parts if p]).strip()
            cand = raw.split('\n')[0].strip().strip('"').strip("'")

            # Normalize and validate
            cand_norm = normalize_reference(cand)

            # Must parse as a Bible reference
            parsed = parse_reference(cand_norm)
            if not parsed:
                raise RuntimeError(f'Model output not recognized as a reference: {cand!r}')

            # Must differ from current verse
            if current_verse and same_reference(current_verse, cand_norm):
                raise RuntimeError(f'Model suggested same verse as existing: {cand_norm!r}')

            # Must be 1–4 verses total
            _, _, verses = parsed
            total = count_verses(verses)
            if total < 1 or total > 4:
                raise RuntimeError(f'Model suggested {total} verses (must be 1–4): {cand_norm!r}')

            return cand_norm
        except (APIStatusError, Exception) as e:
            last_err = e
            if attempt < retries:
                time.sleep(retry_delay)
            else:
                raise RuntimeError(f'Claude reading generation failed after {retries} attempts: {e}') from e

    raise RuntimeError(f'Claude reading generation failed: {last_err}')


def load_json_records(data: Any, filename: Path):
    if isinstance(data, list):
        return data, None, None
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            return data[list_keys[0]], data, list_keys[0]
        raise ValueError(f'{filename}: expected a list or a dict with a single list of records')
    raise ValueError(f'{filename}: unsupported JSON structure')


def process_file(
    path: Path,
    preview: bool,
    client: Anthropic,
    model: str,
    temperature: float,
    max_tokens: int,
) -> int:
    """
    For each record:
      - If reading has content (non-empty after strip): leave untouched.
      - If reading == "" (empty/whitespace), call Claude to propose a 1–4 verse reading
        that differs from 'verse'; set reading and ai_reading=true.
    In preview mode, show before/after only for changed records.
    """
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        records, container, key = load_json_records(raw, path)
    except Exception as e:
        print(f'[ERROR] {path}: cannot read/parse JSON: {e}')
        return 2

    updated_records: List[Dict[str, Any]] = []
    preview_items: List[Tuple[int, Dict[str, str]]] = []

    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            updated_records.append(rec)
            continue

        reading_val = rec.get('reading', '')
        if isinstance(reading_val, str) and reading_val.strip() != '':
            # Leave existing reading as-is
            updated_records.append(rec)
            continue

        # If here, reading is empty or not a string
        reflection = (rec.get('reflection') or '').strip()
        current_verse = (rec.get('verse') or '').strip()

        # If reflection is empty, we can still attempt—but quality may drop.
        try:
            new_reading = call_claude_for_reading(
                client=client,
                reflection=reflection,
                current_verse=current_verse,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            # Log the error and leave record unchanged
            print(f'[ERROR] {path}:{idx} AI reading generation failed: {e}')
            updated_records.append(rec)
            continue

        rec_copy = dict(rec)
        rec_copy['reading'] = new_reading
        rec_copy['ai_reading'] = True

        updated_records.append(rec_copy)

        if preview:
            before_r = reading_val if isinstance(reading_val, str) else ''
            preview_items.append(
                (
                    idx,
                    {
                        'before_reading': before_r,
                        'after_reading': new_reading,
                        'ai_reading': 'true',
                    },
                )
            )

    if preview:
        if preview_items:
            print(f'\n=== Preview: {path} ===')
            for idx, payload in preview_items:
                print(SEPARATOR)
                print(f'Record {idx}:')
                print(f'- reading (before): {payload["before_reading"]!r}')
                print(f'- reading (after) : {payload["after_reading"]!r}')
                print(f'- ai_reading      : {payload["ai_reading"]}')
            print(SEPARATOR)
        return 0

    # Write mode
    try:
        if container is None:
            out = updated_records
        else:
            container[key] = updated_records
            out = container
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'[OK] {path}: updated readings where empty')
        return 0
    except Exception as e:
        print(f'[ERROR] {path}: failed to write updates: {e}')
        return 2


def main():
    parser = argparse.ArgumentParser(
        description="Generate 'reading' references with Claude for records where reading is empty; ensure different from 'verse' and keep to 1–4 verses."
    )
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    parser.add_argument('--preview', action='store_true', help='Show before/after without writing files')
    parser.add_argument(
        '--model',
        default=DEFAULT_MODEL,
        help=f'Claude model (default: {DEFAULT_MODEL})',
    )
    parser.add_argument(
        '--temperature',
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f'Sampling temperature (default: {DEFAULT_TEMPERATURE})',
    )
    parser.add_argument(
        '--max-tokens',
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f'Max tokens for suggestion (default: {DEFAULT_MAX_TOKENS})',
    )
    args = parser.parse_args()

    # Prefer CLAUDE_API_KEY, fall back to ANTHROPIC_API_KEY for compatibility
    api_key = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print('[ERROR] CLAUDE_API_KEY (or ANTHROPIC_API_KEY) is not set.')
        sys.exit(2)

    client = Anthropic(api_key=api_key)

    exit_code = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] {path}: not found')
            exit_code = max(exit_code, 2)
            continue
        rc = process_file(
            path=path,
            preview=args.preview,
            client=client,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        exit_code = max(exit_code, rc)

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
