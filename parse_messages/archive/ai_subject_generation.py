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
TARGET_SUBJECT = 'thoughts to live by'

# Defaults (tune as needed)
DEFAULT_MODEL = os.getenv('CLAUDE_SUBJECT_MODEL', 'claude-3-haiku-20240307')
DEFAULT_MAX_TOKENS = int(os.getenv('CLAUDE_SUBJECT_MAX_TOKENS', '40'))
DEFAULT_TEMPERATURE = float(os.getenv('CLAUDE_SUBJECT_TEMPERATURE', '0.4'))
DEFAULT_RETRIES = int(os.getenv('CLAUDE_SUBJECT_RETRIES', '3'))
DEFAULT_RETRY_DELAY = float(os.getenv('CLAUDE_SUBJECT_RETRY_DELAY', '1.5'))


def is_target_subject(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() == TARGET_SUBJECT


def clean_subject_line(s: str) -> str:
    if not isinstance(s, str):
        return ''
    s = s.strip().strip('"').strip("'")
    s = re.sub(r'\s+', ' ', s).strip()
    s = s.strip(' -–—:;,.')
    if len(s) > 90:
        s = s[:90].rstrip()
    s = s.split('\n')[0].strip()
    words = s.split()
    if len(words) > 8:
        s = ' '.join(words[:8]).rstrip(',.:;!-')
    return s


def build_claude_messages(reflection: str) -> List[Dict[str, str]]:
    if not isinstance(reflection, str) or not reflection.strip():
        reflection = (
            'Write a concise, encouraging devotional email subject rooted in hope, faith, and practical wisdom.'
        )
    instr = (
        'You write concise, compelling devotional email subjects.\n'
        '- 3 to 5 words\n'
        '- Title Case (Capitalize Major Words; keep small words lowercase unless first/last)\n'
        '- No quotes, no emojis, no verse references\n'
        '- Reflect the core idea of the reflection\n'
        'Output: one subject line only.'
    )
    return [{'role': 'user', 'content': f'{instr}\n\nReflection:\n{reflection.strip()}\n'}]


def call_claude_for_subject(
    client: Anthropic,
    reflection: str,
    model: str,
    max_tokens: int,
    temperature: float,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> str:
    messages = build_claude_messages(reflection)
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
            )
            text_parts: List[str] = []
            for block in resp.content or []:
                # anthropic>=0.25 returns objects; handle dict fallback
                if getattr(block, 'type', None) == 'text':
                    text_parts.append(block.text)
                elif isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
            raw = ' '.join([p for p in text_parts if p]).strip()
            subject = clean_subject_line(raw)
            if not subject:
                raise RuntimeError('Empty AI subject result after cleaning.')
            return subject
        except (APIStatusError, Exception) as e:
            last_err = e
            if attempt < retries:
                time.sleep(retry_delay)
            else:
                raise RuntimeError(f'Claude generation failed after {retries} attempts: {e}') from e
    raise RuntimeError(f'Claude generation failed: {last_err}')


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

        subject_val = rec.get('subject')
        if not is_target_subject(subject_val):
            updated_records.append(rec)
            continue

        reflection = rec.get('reflection', '')

        try:
            new_subject = call_claude_for_subject(
                client=client,
                reflection=reflection,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            print(f'[ERROR] {path}:{idx} AI subject generation failed: {e}')
            updated_records.append(rec)
            continue

        rec_copy = dict(rec)
        rec_copy['subject'] = new_subject
        rec_copy['ai_subject'] = True
        updated_records.append(rec_copy)

        if preview:
            before_s = subject_val if isinstance(subject_val, str) else ''
            preview_items.append(
                (
                    idx,
                    {
                        'before_subject': before_s,
                        'after_subject': new_subject,
                        'ai_subject': 'true',
                    },
                )
            )

    if preview:
        if preview_items:
            print(f'\n=== Preview: {path} ===')
            for idx, payload in preview_items:
                print(SEPARATOR)
                print(f'Record {idx}:')
                print(f'- subject (before): {payload["before_subject"]}')
                print(f'- subject (after) : {payload["after_subject"]}')
                print(f'- ai_subject      : {payload["ai_subject"]}')
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
        print(f'[ERROR] {path}: failed to write updates: {e}')
        return 2


def main():
    parser = argparse.ArgumentParser(
        description='Use Claude to generate subjects for records where subject equals "thoughts to live by".'
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
        help=f'Max tokens for subject (default: {DEFAULT_MAX_TOKENS})',
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
