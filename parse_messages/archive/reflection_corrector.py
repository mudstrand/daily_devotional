#!/usr/bin/env python3
"""
AI Reflection Corrector Script

Processes JSON files to correct spelling, punctuation, and formatting errors
in "reflection" fields using Claude AI. Standardizes quotes and whitespace,
removes \n characters, and strips any model-added headers like
"CORRECTED_TEXT:" or "CORRECTIONS_NEEDED" to prevent leaking markers.

Preview mode now prints:
-  ORIGINAL
-  CORRECTED: "<first 20 chars...>"
-  FULL CORRECTED TEXT: "<entire corrected text>"
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
client = anthropic.Anthropic(
    api_key=os.getenv('CLAUDE_API_KEY'),
)

CORRECTED_DIR = 'ai_corrected_reflections'

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
    """Extract the message_id from the record."""
    if 'message_id' not in record:
        raise ValueError("Record missing required 'message_id' field")
    return str(record['message_id'])


def standardize_text_formatting(text: str) -> str:
    """Standardize quotes to straight quotes and remove \\n characters, normalize spaces."""
    # Handle escaped quotes
    text = text.replace('\\"', '"')

    # Remove literal backslash-n and real newlines
    text = re.sub(r'\\n', ' ', text)
    text = text.replace('\n', ' ')

    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Retain straight quotes; keep simple apostrophe handling
    text = re.sub(r"(\s|^)'(?=\w)", r"\1'", text)
    text = re.sub(r"(?<=\w)'(?=\s|[.,:;!?]|$)", r"'", text)
    text = re.sub(r"(?<=[.,:;!?])'(?=\s|[.,:;!?]|$)", r"'", text)

    return text


def get_cached_correction(message_id: str) -> Tuple[Optional[str], bool]:
    """Check if we already have a cached correction. Returns (correction_text, cache_exists)."""
    cache_file = Path(CORRECTED_DIR) / f'{message_id}_reflection.txt'
    if cache_file.exists():
        with open(cache_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content == 'okay':
                return None, True  # No correction needed, but cache exists
            else:
                return content, True  # Correction text, cache exists
    return None, False  # No cache


def save_correction(message_id: str, corrected_text: Optional[str]):
    """Save the correction to cache file."""
    Path(CORRECTED_DIR).mkdir(exist_ok=True)
    cache_file = Path(CORRECTED_DIR) / f'{message_id}_reflection.txt'
    content = corrected_text if corrected_text else 'okay'
    with open(cache_file, 'w', encoding='utf-8') as f:
        f.write(content)


def get_renamed_filename(original_path: str) -> Optional[str]:
    """Get the new filename for renaming parsed_<nnnn>.json to <nnnn>.json"""
    filename = os.path.basename(original_path)
    dirname = os.path.dirname(original_path)
    match = re.match(r'^parsed_(\d+)\.json$', filename)
    if match:
        number = match.group(1)
        new_filename = f'{number}.json'
        return os.path.join(dirname, new_filename)
    return None


def clean_claude_response(response_text: str, original_text: str) -> Optional[str]:
    """Clean up Claude's response and extract just the corrected text."""
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
        # Extra variants to strip
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

    # Strip Markdown code fences if present
    cleaned = re.sub(r'^```(?:\w+)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)

    # Remove unwanted prefixes (case-insensitive, allow optional whitespace)
    for prefix in unwanted_prefixes:
        pattern = r'^\s*' + re.escape(prefix) + r'\s*'
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()

    # Remove leading punctuation noise
    cleaned = re.sub(r'^[:~\-–—\s]+', '', cleaned)

    # Normalize line breaks and spaces
    cleaned = cleaned.replace('\\n', ' ')
    cleaned = cleaned.replace('\n', ' ')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # If identical to original, treat as no change
    if cleaned == original_text:
        return None

    # Guard against empty/too-short results
    if not cleaned or len(cleaned) < 2:
        return None

    return cleaned


def correct_reflection_with_ai(reflection_text: str) -> Optional[str]:
    """Use Claude AI to correct spelling, punctuation, and formatting errors."""
    prompt = f"""Fix only spelling, punctuation, capitalization, and spacing errors in the text below.
Do not add any headers, labels, or explanations. Output only the corrected text.
Do NOT output strings like: CORRECTED_TEXT:, CORRECTIONS_NEEDED, Corrected:, Edited:, Result:.

If no corrections are needed, respond with exactly: NO_CHANGES_NEEDED

Text:
{reflection_text}"""

    try:
        response = client.messages.create(
            model='claude-3-haiku-20240307',
            max_tokens=2000,
            temperature=0.1,
            system='You are a proofreader. Output only the corrected text with no labels or commentary. Never add headers or markers.',
            messages=[{'role': 'user', 'content': prompt}],
        )

        raw_response = response.content[0].text.strip()

        # Handle 'no changes' in a tolerant way
        if re.search(r'\bno[_\s-]*changes[_\s-]*needed\b', raw_response, re.I):
            return None

        # Clean the response
        cleaned_response = clean_claude_response(raw_response, reflection_text)

        # Final guard: if any marker still appears, reject it as no-change
        if cleaned_response and contains_marker(cleaned_response):
            cleaned_response = clean_claude_response(cleaned_response, reflection_text)
            if cleaned_response and contains_marker(cleaned_response):
                return None

        return cleaned_response

    except Exception as e:
        print(f'❌ Error calling Claude API for correction: {e}')
        return None


def process_record(record: Dict[str, Any], preview_mode: bool = False) -> Tuple[Dict[str, Any], bool]:
    """Process a single JSON record. Returns (updated_record, was_corrected)."""
    try:
        message_id = get_message_id(record)
    except ValueError as e:
        if preview_mode:
            print(f'⚠️  {e}')
        return record, False

    if 'reflection' not in record:
        if preview_mode:
            print(f"⚠️  Message ID {message_id}: No 'reflection' field found")
        return record, False

    original_reflection = record['reflection']

    # Step 1: Check cache for AI correction first (before standardization)
    cached_correction, correction_cache_exists = get_cached_correction(message_id)
    if correction_cache_exists:
        if cached_correction is not None:
            # We have a cached AI correction - apply standardization to it
            final_reflection = standardize_text_formatting(cached_correction)
            needs_update = True
            correction_source = 'CACHED AI+QUOTES'
        else:
            # Cached as "okay" - just apply standardization to original
            standardized_reflection = standardize_text_formatting(original_reflection)
            if standardized_reflection != original_reflection:
                final_reflection = standardized_reflection
                needs_update = True
                correction_source = 'QUOTES ONLY'
            else:
                final_reflection = original_reflection
                needs_update = False
                correction_source = 'CACHED OK'
        correction_cache_hit = True
    else:
        # No cache - get AI correction first, then standardize
        try:
            ai_correction = correct_reflection_with_ai(original_reflection)
            correction_cache_hit = False

            if ai_correction is not None:
                # AI made corrections - standardize the corrected text
                final_reflection = standardize_text_formatting(ai_correction)
                needs_update = True
                correction_source = 'NEW AI+QUOTES'
                # Cache the AI correction (before standardization)
                save_correction(message_id, ai_correction)
            else:
                # AI made no corrections - just standardize original
                standardized_reflection = standardize_text_formatting(original_reflection)
                if standardized_reflection != original_reflection:
                    final_reflection = standardized_reflection
                    needs_update = True
                    correction_source = 'QUOTES ONLY'
                else:
                    final_reflection = original_reflection
                    needs_update = False
                    correction_source = 'NEW OK'
                # Cache that no AI correction was needed
                save_correction(message_id, None)

        except Exception as e:
            if preview_mode:
                print(f'❌ Message ID {message_id}: API Error - {e}')
            return record, False

    # Update record if any changes were made
    if needs_update:
        updated_record = record.copy()
        updated_record['reflection'] = final_reflection
        updated_record['ai_reflection_corrected'] = True

        if preview_mode:
            cache_indicator = ' [CACHED]' if correction_cache_hit else ' [NEW]'

            print(f'\n{"=" * 60}')
            print(f'Message ID: {message_id}{cache_indicator} [{correction_source}]')
            print(f'{"=" * 60}')
            print('ORIGINAL:')
            print(f'"{original_reflection}"')

            # One-line summary with first 20 characters of corrected text
            snippet_source = final_reflection.lstrip()
            snippet = snippet_source[:20].replace('\n', ' ')
            suffix = '...' if len(snippet_source) > 20 else ''
            print(f'\nCORRECTED: "{snippet}{suffix}"')

            # Then print the full corrected text
            print('FULL CORRECTED TEXT:')
            print(f'"{final_reflection}"')
            print(f'{"=" * 60}')

        return updated_record, True
    else:
        if preview_mode:
            cache_indicator = ' [CACHED]' if correction_cache_hit else ' [NEW]'
            print(f'✓ Message ID: {message_id}{cache_indicator} [{correction_source}] - No changes needed')

        return record, False


def load_json_file(file_path: str) -> List[Dict[str, Any]]:
    """Load JSON file and return list of records."""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Handle both single objects and arrays
    if isinstance(data, list):
        return data
    else:
        return [data]


def save_json_file(file_path: str, records: List[Dict[str, Any]]):
    """Save records back to JSON file."""
    # Determine if original was a single object or array
    with open(file_path, 'r', encoding='utf-8') as f:
        original_data = json.load(f)

    if isinstance(original_data, list):
        data_to_save = records
    else:
        data_to_save = records[0] if records else {}

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data_to_save, f, indent=2, ensure_ascii=False)


def rename_file_after_processing(original_path: str, preview_mode: bool) -> bool:
    """Rename parsed_<nnnn>.json to <nnnn>.json after processing."""
    new_path = get_renamed_filename(original_path)
    if new_path is None:
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
    parser = argparse.ArgumentParser(description='Correct reflection fields in JSON files using Claude AI')
    parser.add_argument('files', nargs='+', help='JSON files to process')
    parser.add_argument('--preview', action='store_true', help='Preview changes without making them')

    args = parser.parse_args()

    # Check for Claude API key
    if not os.getenv('CLAUDE_API_KEY'):
        print('Error: CLAUDE_API_KEY environment variable not set')
        print("Please set it with: export CLAUDE_API_KEY='your-api-key'")
        sys.exit(1)

    total_files = 0
    total_records = 0
    total_corrected = 0
    total_renamed = 0

    print(f'\n🔄 Processing {len(args.files)} file(s) in {"PREVIEW" if args.preview else "UPDATE"} mode...')
    print('📝 Applying: quote/space normalization + \\n removal + AI corrections')

    for file_path in args.files:
        if not os.path.exists(file_path):
            print(f'Warning: File {file_path} not found, skipping...')
            continue

        try:
            print(f'\n{"=" * 70}')
            print(f'PROCESSING: {file_path}')
            print(f'{"=" * 70}')

            records = load_json_file(file_path)
            updated_records = []
            file_corrections = 0

            for i, record in enumerate(records, 1):
                if args.preview:
                    print(f'\n--- Record {i}/{len(records)} ---')

                updated_record, was_corrected = process_record(record, args.preview)
                updated_records.append(updated_record)

                if was_corrected:
                    file_corrections += 1
                    total_corrected += 1

            # Save the file (even if no corrections were made)
            if not args.preview:
                save_json_file(file_path, updated_records)

            # Rename the file after processing
            renamed = rename_file_after_processing(file_path, args.preview)
            if renamed:
                total_renamed += 1

            print(f'\n{"=" * 70}')
            if not args.preview and file_corrections > 0:
                print(f'✅ UPDATED {file_corrections}/{len(records)} records in {os.path.basename(file_path)}')
            elif args.preview:
                print(f'📋 WOULD UPDATE {file_corrections}/{len(records)} records in {os.path.basename(file_path)}')
            else:
                print(f'✅ NO CORRECTIONS needed for {os.path.basename(file_path)}')

            total_files += 1
            total_records += len(records)

        except Exception as e:
            print(f'❌ Error processing {file_path}: {e}')

    print(f'\n{"=" * 70}')
    print('📊 SUMMARY')
    print(f'{"=" * 70}')
    print(f'Files processed: {total_files}')
    print(f'Total records: {total_records}')
    print(f'Records corrected: {total_corrected}')
    print(f'Files renamed: {total_renamed}')

    if args.preview:
        print(f'\n💡 Run without --preview to apply changes and rename files')
        print(f'💾 Corrections cached in: {CORRECTED_DIR}/')
    else:
        print(f'\n💾 Corrections cached in: {CORRECTED_DIR}/')
        print(f'✨ Processing complete!')


if __name__ == '__main__':
    main()
