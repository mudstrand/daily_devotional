#!/usr/bin/env python3
"""
AI Reflection Corrector Script

Processes JSON files to correct spelling, punctuation, and formatting errors
in "reflection" fields using Claude AI.
"""

import json
import os
import sys
import argparse
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
import anthropic

# Initialize Claude client with explicit version
client = anthropic.Anthropic(
    api_key=os.getenv("CLAUDE_API_KEY"),
)

CORRECTED_DIR = "ai_corrected_reflections"


def get_message_id(record: Dict[str, Any]) -> str:
    """Extract the message_id from the record."""
    if "message_id" not in record:
        raise ValueError("Record missing required 'message_id' field")
    return str(record["message_id"])


def get_cached_correction(message_id: str) -> Optional[str]:
    """Check if we already have a cached correction for this message."""
    cache_file = Path(CORRECTED_DIR) / f"{message_id}_reflection.txt"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return content if content != "okay" else None
    return None


def save_correction(message_id: str, corrected_text: Optional[str]):
    """Save the correction to cache file."""
    Path(CORRECTED_DIR).mkdir(exist_ok=True)
    cache_file = Path(CORRECTED_DIR) / f"{message_id}_reflection.txt"

    content = corrected_text if corrected_text else "okay"
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write(content)


def get_renamed_filename(original_path: str) -> Optional[str]:
    """Get the new filename for renaming parsed_<nnnn>.json to <nnnn>.json"""
    filename = os.path.basename(original_path)
    dirname = os.path.dirname(original_path)

    # Match pattern parsed_<nnnn>.json
    match = re.match(r"^parsed_(\d+)\.json$", filename)
    if match:
        number = match.group(1)
        new_filename = f"{number}.json"
        return os.path.join(dirname, new_filename)
    return None


def correct_reflection_with_ai(reflection_text: str) -> Optional[str]:
    """Use Claude AI to correct spelling, punctuation, and formatting errors."""
    prompt = f"""Please correct any spelling, punctuation, capitalization, and spacing errors in the following text. 
Make ONLY mechanical corrections - do not change the meaning, tone, or wording in any way. 
If the text needs no corrections, respond with exactly "NO_CHANGES_NEEDED".

Text to correct:
{reflection_text}

Provide only the corrected text as your response, or "NO_CHANGES_NEEDED" if no corrections are needed."""

    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2000,
            temperature=0.1,
            system="You are a proofreader that fixes only mechanical errors (spelling, punctuation, capitalization, spacing) without changing meaning or wording.",
            messages=[{"role": "user", "content": prompt}],
        )

        corrected = response.content[0].text.strip()

        if corrected == "NO_CHANGES_NEEDED" or corrected == reflection_text:
            return None

        return corrected

    except Exception as e:
        print(f"❌ Error calling Claude API: {e}")
        return None


def process_record(
    record: Dict[str, Any], preview_mode: bool = False
) -> tuple[Dict[str, Any], bool]:
    """Process a single JSON record."""
    try:
        message_id = get_message_id(record)
    except ValueError as e:
        if preview_mode:
            print(f"⚠️  {e}")
        return record, False

    if "reflection" not in record:
        if preview_mode:
            print(f"⚠️  Message ID {message_id}: No 'reflection' field found")
        return record, False

    original_reflection = record["reflection"]

    # Check cache first
    cached_correction = get_cached_correction(message_id)
    if cached_correction is not None:
        corrected_reflection = cached_correction
        needs_correction = True
        cache_hit = True
    else:
        # Use AI to check and correct
        try:
            corrected_reflection = correct_reflection_with_ai(original_reflection)
            needs_correction = corrected_reflection is not None
            cache_hit = False

            # Cache the result (even in preview mode for efficiency)
            save_correction(message_id, corrected_reflection)
        except Exception as e:
            if preview_mode:
                print(f"❌ Message ID {message_id}: API Error - {e}")
            return record, False

    if needs_correction:
        updated_record = record.copy()
        updated_record["reflection"] = corrected_reflection
        updated_record["ai_reflection_corrected"] = True

        if preview_mode:
            cache_status = " [FROM CACHE]" if cache_hit else " [NEW]"
            print(f"\n{'=' * 60}")
            print(f"Message ID: {message_id}{cache_status}")
            print(f"{'=' * 60}")
            print("ORIGINAL:")
            print(f'"{original_reflection}"')
            print("\nCORRECTED:")
            print(f'"{corrected_reflection}"')
            print(f"{'=' * 60}")

        return updated_record, True
    else:
        if preview_mode:
            cache_status = " [CACHED: OK]" if cache_hit else " [NEW: OK]"
            print(f"✓ Message ID: {message_id}{cache_status} - No changes needed")
        return record, False


def load_json_file(file_path: str) -> List[Dict[str, Any]]:
    """Load JSON file and return list of records."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Handle both single objects and arrays
    if isinstance(data, list):
        return data
    else:
        return [data]


def save_json_file(file_path: str, records: List[Dict[str, Any]]):
    """Save records back to JSON file."""
    # Determine if original was a single object or array
    with open(file_path, "r", encoding="utf-8") as f:
        original_data = json.load(f)

    if isinstance(original_data, list):
        data_to_save = records
    else:
        data_to_save = records[0] if records else {}

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, indent=2, ensure_ascii=False)


def rename_file_after_processing(original_path: str, preview_mode: bool) -> bool:
    """Rename parsed_<nnnn>.json to <nnnn>.json after processing."""
    new_path = get_renamed_filename(original_path)
    if new_path is None:
        return False

    if preview_mode:
        print(
            f"📝 Would rename: {os.path.basename(original_path)} → {os.path.basename(new_path)}"
        )
        return True

    try:
        if os.path.exists(new_path):
            print(f"⚠️  Target file {new_path} already exists, skipping rename")
            return False

        os.rename(original_path, new_path)
        print(
            f"📝 Renamed: {os.path.basename(original_path)} → {os.path.basename(new_path)}"
        )
        return True
    except Exception as e:
        print(f"❌ Error renaming {original_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Correct reflection fields in JSON files using Claude AI"
    )
    parser.add_argument("files", nargs="+", help="JSON files to process")
    parser.add_argument(
        "--preview", action="store_true", help="Preview changes without making them"
    )

    args = parser.parse_args()

    # Check for Claude API key
    if not os.getenv("CLAUDE_API_KEY"):
        print("Error: CLAUDE_API_KEY environment variable not set")
        print("Please set it with: export CLAUDE_API_KEY='your-api-key'")
        sys.exit(1)

    total_files = 0
    total_records = 0
    total_corrected = 0
    total_renamed = 0

    print(
        f"\n🔄 Processing {len(args.files)} file(s) in {'PREVIEW' if args.preview else 'UPDATE'} mode..."
    )

    for file_path in args.files:
        if not os.path.exists(file_path):
            print(f"Warning: File {file_path} not found, skipping...")
            continue

        try:
            print(f"\n{'=' * 70}")
            print(f"PROCESSING: {file_path}")
            print(f"{'=' * 70}")

            records = load_json_file(file_path)
            updated_records = []
            file_corrections = 0

            for i, record in enumerate(records, 1):
                if args.preview:
                    print(f"\n--- Record {i}/{len(records)} ---")

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

            print(f"\n{'=' * 70}")
            if not args.preview and file_corrections > 0:
                print(
                    f"✅ UPDATED {file_corrections}/{len(records)} records in {os.path.basename(file_path)}"
                )
            elif args.preview:
                print(
                    f"📋 WOULD UPDATE {file_corrections}/{len(records)} records in {os.path.basename(file_path)}"
                )
            else:
                print(f"✅ NO CORRECTIONS needed for {os.path.basename(file_path)}")

            total_files += 1
            total_records += len(records)

        except Exception as e:
            print(f"❌ Error processing {file_path}: {e}")

    print(f"\n{'=' * 70}")
    print("📊 SUMMARY")
    print(f"{'=' * 70}")
    print(f"Files processed: {total_files}")
    print(f"Total records: {total_records}")
    print(f"Records corrected: {total_corrected}")
    print(f"Files renamed: {total_renamed}")

    if args.preview:
        print(f"\n💡 Run without --preview to apply changes and rename files")
        print(f"💾 Corrections cached in: {CORRECTED_DIR}/")
    else:
        print(f"\n💾 Corrections cached in: {CORRECTED_DIR}/")
        print(f"✨ Processing complete!")


if __name__ == "__main__":
    main()
