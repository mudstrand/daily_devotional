#!/usr/bin/env python3
"""
AI Prayer Corrector Script (mirror of reflection flow, scoped to 'prayer')

-   Corrects spelling, punctuation, capitalization, and spacing for the "prayer" field.
-   Caches AI responses in ai_corrected_prayers/<message_id>_prayer.txt:
    * "okay"   -> no AI changes
    * <text>   -> corrected text from AI (pre-standardization)
-   Adds/maintains ai_prayer_corrected boolean (default False); sets to True only when AI modifies the prayer text.
-   Preview mode prints ORIGINAL, one-line CORRECTED snippet (first 20 chars), and FULL CORRECTED TEXT.
-   Non-preview mode writes updated JSON in-place and renames <nnnn>.json -> p_<nnnn>.json.
"""

import json
import os
import sys
import argparse
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import anthropic

# Initialize Claude client
client = anthropic.Anthropic(api_key=os.getenv('CLAUDE_API_KEY'))

# Persistent cache directory for prayer corrections
CACHE_DIR = Path('ai_corrected_prayers')

# Markers we never want to appear in the output
HEADER_MARKERS = (
    'CORRECTED_TEXT',
    'CORRECTIONS_NEEDED',
    'CORRECTION_NEEDED',
    'CORRECTED',
    'CORRECTION',
    'EDITED',
    'EDITED TEXT',
    'RESULT',
    'OUTPUT',
    'Here is the corrected text',
    'Corrected text',
    'Corrected version',
    'Fixed version',
    'Corrections needed',
    'Important',
)


def contains_marker(s: str) -> bool:
    low = s.lower()
    return any(m.lower() in low for m in HEADER_MARKERS)


def get_message_id(record: Dict[str, Any]) -> str:
    if 'message_id' not in record:
        raise ValueError("Record missing required 'message_id' field")
    return str(record['message_id'])


def standardize_text_formatting(text: str) -> str:
    text = text.replace('\\"', '"')
    text = re.sub(r'\\n', ' ', text)
    text = text.replace('\n', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r"(\s|^)'(?=\w)", r"\1'", text)
    text = re.sub(r"(?<=\w)'(?=\s|[.,:;!?]|$)", r"'", text)
    text = re.sub(r"(?<=[.,:;!?])'(?=\s|[.,:;!?]|$)", r"'", text)
    return text


def cache_path(message_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f'{message_id}_prayer.txt'


def get_cached_correction(message_id: str) -> Tuple[Optional[str], bool]:
    path = cache_path(message_id)
    if not path.exists():
        return None, False
    content = path.read_text(encoding='utf-8').strip()
    if content == 'okay':
        return None, True
    return content, True


def save_correction(message_id: str, corrected_text: Optional[str]) -> None:
    path = cache_path(message_id)
    path.write_text(corrected_text if corrected_text else 'okay', encoding='utf-8')


def get_renamed_filename(original_path: str) -> Optional[str]:
    """
    Rename <nnnn>.json to p_<nnnn>.json after processing.
    If filename doesn't match the pattern, return None (no rename).
    """
    filename = os.path.basename(original_path)
    dirname = os.path.dirname(original_path)
    m = re.match(r'^(\d+)\.json$', filename)
    if m:
        number = m.group(1)
        return os.path.join(dirname, f'p_{number}.json')
    return None


def clean_claude_response(response_text: str, original_text: str) -> Optional[str]:
    unwanted_prefixes = [
        'IMPORTANT: Corrections needed.',
        'CORRECTED:',
        'Corrected text:',
        'Here is the corrected text:',
        'Fixed version:',
        'IMPORTANT:',
        'Corrections needed:',
        'CORRECTED VERSION:',
        "Here's the corrected version:",
        'CORRECTED_TEXT:',
        'CORRECTIONS_NEEDED',
        'CORRECTIONS_NEEDED:',
        'CORRECTION_NEEDED',
        'CORRECTION_NEEDED:',
        'CORRECTIONS:',
        'EDITED:',
        'EDITED TEXT:',
        'RESULT:',
        'OUTPUT:',
    ]
    cleaned = response_text.strip()
    cleaned = re.sub(r'^```(?:\w+)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    for prefix in unwanted_prefixes:
        cleaned = re.sub(r'^\s*' + re.escape(prefix) + r'\s*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'^[:~\-–—\s]+', '', cleaned)
    cleaned = cleaned.replace('\\n', ' ').replace('\n', ' ')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned == original_text:
        return None
    if not cleaned or len(cleaned) < 2:
        return None
    return cleaned


def correct_prayer_with_ai(prayer_text: str) -> Optional[str]:
    prompt = f"""Fix only spelling, punctuation, capitalization, and spacing errors in the prayer text below.
Do not add any headers, labels, or explanations. Output only the corrected text.
Do NOT output strings like: CORRECTED_TEXT:, CORRECTIONS_NEEDED, Corrected:, Edited:, Result:.

If no corrections are needed, respond with exactly: NO_CHANGES_NEEDED

Text:
{prayer_text}"""
    try:
        response = client.messages.create(
            model='claude-3-haiku-20240307',
            max_tokens=2000,
            temperature=0.1,
            system='You are a proofreader. Output only the corrected text with no labels or commentary. Never add headers or markers.',
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = response.content[0].text.strip()
        if re.search(r'\bno[_\s-]*changes[_\s-]*needed\b', raw, re.I):
            return None
        cleaned = clean_claude_response(raw, prayer_text)
        if cleaned and contains_marker(cleaned):
            cleaned = clean_claude_response(cleaned, prayer_text)
            if cleaned and contains_marker(cleaned):
                return None
        return cleaned
    except Exception as e:
        print(f'❌ Error calling Claude API for correction: {e}')
        return None


def process_prayer(record: Dict[str, Any], preview_mode: bool = False) -> Tuple[Dict[str, Any], bool]:
    updated = record.copy()
    message_id = get_message_id(record)
    updated.setdefault('ai_prayer_corrected', False)

    if 'prayer' not in record:
        if preview_mode:
            print(f"⚠️  Message ID {message_id}: No 'prayer' field found")
        return updated, False

    original = record['prayer']

    cached, cache_exists = get_cached_correction(message_id)
    cache_hit = cache_exists

    if cache_exists:
        if cached is not None:
            final_text = standardize_text_formatting(cached)
            ai_changed = True
            source = 'CACHED AI+QUOTES'
        else:
            standardized = standardize_text_formatting(original)
            if standardized != original:
                final_text = standardized
                ai_changed = False
                source = 'QUOTES ONLY'
            else:
                final_text = original
                ai_changed = False
                source = 'CACHED OK'
    else:
        ai = correct_prayer_with_ai(original)
        if ai is not None:
            final_text = standardize_text_formatting(ai)
            ai_changed = True
            source = 'NEW AI+QUOTES'
            save_correction(message_id, ai)
        else:
            standardized = standardize_text_formatting(original)
            if standardized != original:
                final_text = standardized
                ai_changed = False
                source = 'QUOTES ONLY'
            else:
                final_text = original
                ai_changed = False
                source = 'NEW OK'
            save_correction(message_id, None)

    changed = final_text != original
    if changed:
        updated['prayer'] = final_text
        if ai_changed:
            updated['ai_prayer_corrected'] = True

        if preview_mode:
            cache_indicator = ' [CACHED]' if cache_hit else ' [NEW]'
            print(f'\n{"-" * 60}')
            print(f'PRAYER update for Message ID {message_id}{cache_indicator} [{source}]')
            print(f'{"-" * 60}')
            print('ORIGINAL:')
            print(f'"{original}"')
            snippet_source = final_text.lstrip()
            snippet = snippet_source[:20].replace('\n', ' ')
            suffix = '...' if len(snippet_source) > 20 else ''
            print(f'\nCORRECTED: "{snippet}{suffix}"')
            print('FULL CORRECTED TEXT:')
            print(f'"{final_text}"')
            print(f'{"-" * 60}')
    else:
        if preview_mode:
            print(f'✓ Message ID {message_id} [prayer] - No changes needed')

    return updated, changed and ai_changed


def load_json_file(path: str) -> List[Dict[str, Any]]:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def save_json_file(path: str, records: List[Dict[str, Any]]):
    with open(path, 'r', encoding='utf-8') as f:
        original = json.load(f)
    out = records if isinstance(original, list) else (records[0] if records else {})
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


def rename_to_processed(original_path: str, preview_mode: bool) -> bool:
    """Rename <nnnn>.json -> p_<nnnn>.json."""
    new_path = get_renamed_filename(original_path)
    if not new_path:
        return False
    if preview_mode:
        print(f'📝 Would rename: {os.path.basename(original_path)} → {os.path.basename(new_path)}')
        return True
    try:
        if os.path.exists(new_path):
            print(f'⚠️  Target file {new_path} already exists, skipping rename')
            return False
        os.rename(original_path, new_path)
        print(f'📝 Renamed: {os.path.basename(original_path)} → {os.path.basename(new_path)}')
        return True
    except Exception as e:
        print(f'❌ Error renaming {original_path}: {e}')
        return False


def main():
    parser = argparse.ArgumentParser(description="Correct 'prayer' field in JSON files using Claude AI")
    parser.add_argument('files', nargs='+', help='JSON files to process')
    parser.add_argument('--preview', action='store_true', help='Preview changes without making them')
    args = parser.parse_args()

    if not os.getenv('CLAUDE_API_KEY'):
        print('Error: CLAUDE_API_KEY environment variable not set')
        print("Please set it with: export CLAUDE_API_KEY='your-api-key'")
        sys.exit(1)

    total_files = total_records = total_ai_prayer = total_renamed = 0

    print(f'\n🔄 Processing {len(args.files)} file(s) in {"PREVIEW" if args.preview else "UPDATE"} mode...')
    print('📝 Applying: whitespace normalization + \\n removal + AI corrections (prayer)')

    for file_path in args.files:
        if not os.path.exists(file_path):
            print(f'Warning: File {file_path} not found, skipping...')
            continue
        try:
            print(f'\n{"=" * 70}')
            print(f'PROCESSING: {file_path}')
            print(f'{"=" * 70}')

            records = load_json_file(file_path)
            updated_records: List[Dict[str, Any]] = []

            for i, record in enumerate(records, 1):
                if args.preview:
                    print(f'\n--- Record {i}/{len(records)} ---')
                record.setdefault('ai_prayer_corrected', False)
                updated, ai_changed = process_prayer(record, args.preview)
                if ai_changed:
                    total_ai_prayer += 1
                updated_records.append(updated)

            if not args.preview:
                save_json_file(file_path, updated_records)

            renamed = rename_to_processed(file_path, args.preview)
            if renamed:
                total_renamed += 1

            total_files += 1
            total_records += len(records)
        except Exception as e:
            print(f'❌ Error processing {file_path}: {e}')

    print(f'\n{"=" * 70}')
    print('📊 SUMMARY')
    print(f'{"=" * 70}')
    print(f'Files processed: {total_files}')
    print(f'Total records: {total_records}')
    print(f'Records AI-corrected (prayer): {total_ai_prayer}')
    print(f'Files renamed: {total_renamed}')
    print(f'\n💾 Cache directory: {CACHE_DIR}/')
    if args.preview:
        print('💡 Run without --preview to apply changes and rename files')


if __name__ == '__main__':
    main()
