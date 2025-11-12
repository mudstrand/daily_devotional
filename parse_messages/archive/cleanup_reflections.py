#!/usr/bin/env python3
"""
Reflection Cleanup Script

Fixes quotes, removes errant text, and cleans up \n characters from reflection fields.
No AI calls - just text processing.
"""

import argparse
import json
import os
import re
from typing import Any, Dict, List, Tuple


def standardize_quotes(text: str) -> str:
    """Convert straight quotes to curly quotes."""
    # First, handle escaped quotes and convert them to regular quotes temporarily
    text = text.replace('\\"', '"')

    # Handle double quotes - split and alternate between opening and closing
    parts = text.split('"')
    if len(parts) > 1:
        result = parts[0]
        for i in range(1, len(parts)):
            if i % 2 == 1:  # Odd index = opening quote
                result += '"' + parts[i]
            else:  # Even index = closing quote
                result += '"' + parts[i]
        text = result

    # Handle single quotes (more complex due to apostrophes)
    # Opening single quote: after whitespace or start of string, before a word character
    text = re.sub(r"(\s|^)'(?=\w)", r"\1'", text)

    # Closing single quote: after a word character or punctuation, before whitespace, punctuation, or end
    text = re.sub(r"(?<=\w)'(?=\s|[.,:;!?]|$)", r"'", text)
    text = re.sub(r"(?<=[.,:;!?])'(?=\s|[.,:;!?]|$)", r"'", text)

    return text


def clean_newlines_and_spacing(text: str) -> str:
    """Remove \n characters and fix spacing issues."""
    changes_made = []

    # Remove literal \n sequences (escaped newlines)
    if "\\n" in text:
        text = re.sub(r"\\n", " ", text)
        changes_made.append("literal \\n")

    # Remove actual newline characters
    if "\n" in text:
        text = re.sub(r"\n", " ", text)
        changes_made.append("newlines")

    # Remove carriage returns too
    if "\r" in text:
        text = re.sub(r"\r", " ", text)
        changes_made.append("carriage returns")

    # Clean up multiple spaces that might result from newline removal
    if re.search(r"\s{2,}", text):
        text = re.sub(r"\s+", " ", text)
        changes_made.append("multiple spaces")

    # Strip leading/trailing whitespace
    text = text.strip()

    if changes_made:
        print(f"    → Cleaned: {', '.join(changes_made)}")

    return text


def remove_errant_prefixes(text: str) -> str:
    """Remove unwanted prefixes that might have been added by AI."""

    # Comprehensive list of prefixes that Claude might add
    unwanted_prefixes = [
        "YES_CHANGES_NEEDED",
        "NO_CHANGES_NEEDED",
        "CHANGES_NEEDED",
        "CORRECTIONS_NEEDED",
        "CORRECTIONS NEEDED",
        "IMPORTANT: Corrections needed.",
        "IMPORTANT: Corrections needed",
        "IMPORTANT:",
        "Corrections needed:",
        "Corrections needed",
        "CORRECTED:",
        "CORRECTED VERSION:",
        "CORRECTED TEXT:",
        "Corrected text:",
        "Corrected:",
        "Here is the corrected text:",
        "Here's the corrected text:",
        "Here is the corrected version:",
        "Here's the corrected version:",
        "Fixed version:",
        "Fixed text:",
        "Fixed:",
        "FIXED:",
        "REVISED:",
        "Revised:",
        "UPDATED:",
        "Updated:",
        "REFLECTION:",
        "Reflection:",
        "TEXT:",
        "Text:",
    ]

    original = text
    cleaned = text.strip()

    # First pass - remove prefixes that might be followed by newlines/spaces
    for prefix in unwanted_prefixes:
        # Check for prefix followed by optional whitespace/newlines
        pattern = re.escape(prefix) + r"[\s\n\r]*"
        if re.match(pattern, cleaned, re.IGNORECASE):
            # Find the actual match to see what we're removing
            match = re.match(pattern, cleaned, re.IGNORECASE)
            if match:
                removed_text = match.group(0)
                cleaned = cleaned[len(removed_text) :].strip()
                print(f"    → Removed prefix: '{removed_text.strip()}'")
                break

    # Second pass - exact matches (case sensitive and insensitive)
    for prefix in unwanted_prefixes:
        # Try exact match
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            print(f"    → Removed exact prefix: '{prefix}'")
            break
        # Try case insensitive match
        elif cleaned.lower().startswith(prefix.lower()):
            actual_prefix = cleaned[: len(prefix)]
            cleaned = cleaned[len(prefix) :].strip()
            print(f"    → Removed prefix: '{actual_prefix}'")
            break

    # Remove any leading colons, dashes, or other punctuation that might be left
    before_punctuation = cleaned
    cleaned = re.sub(r"^[:~\-\s]+", "", cleaned)
    if cleaned != before_punctuation:
        removed = before_punctuation[: len(before_punctuation) - len(cleaned)]
        print(f"    → Removed leading punctuation: '{removed}'")

    return cleaned


def process_reflection(text: str) -> Tuple[str, bool]:
    """Process a reflection text and return (cleaned_text, was_changed)."""
    original = text

    # Step 1: Remove errant prefixes
    cleaned = remove_errant_prefixes(text)

    # Step 2: Clean newlines and spacing
    cleaned = clean_newlines_and_spacing(cleaned)

    # Step 3: Standardize quotes
    quotes_before = cleaned
    cleaned = standardize_quotes(cleaned)
    if cleaned != quotes_before:
        print("    → Standardized quotes")

    was_changed = cleaned != original

    return cleaned, was_changed


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


def main():
    parser = argparse.ArgumentParser(
        description="Clean up reflection fields in JSON files"
    )
    parser.add_argument("files", nargs="+", help="JSON files to process")
    parser.add_argument(
        "--preview", action="store_true", help="Preview changes without making them"
    )

    args = parser.parse_args()

    total_files = 0
    total_records = 0
    total_cleaned = 0

    print(
        f"\n🧹 Cleaning {len(args.files)} file(s) in {'PREVIEW' if args.preview else 'UPDATE'} mode..."
    )
    print(
        "📝 Applying: Prefix removal + \\n cleanup + Quote standardization + Spacing fixes"
    )

    for file_path in args.files:
        if not os.path.exists(file_path):
            print(f"Warning: File {file_path} not found, skipping...")
            continue

        try:
            records = load_json_file(file_path)
            updated_records = []
            file_changes = 0
            processed_count = 0

            # First pass: collect all changes
            records_with_changes = []

            for i, record in enumerate(records, 1):
                if "reflection" not in record:
                    updated_records.append(record)
                    continue

                original_reflection = record["reflection"]
                cleaned_reflection, was_changed = process_reflection(
                    original_reflection
                )

                if was_changed:
                    updated_record = record.copy()
                    updated_record["reflection"] = cleaned_reflection
                    updated_records.append(updated_record)
                    file_changes += 1
                    total_cleaned += 1

                    # Store for display
                    records_with_changes.append(
                        {
                            "index": i,
                            "original": original_reflection,
                            "cleaned": cleaned_reflection,
                        }
                    )

                else:
                    updated_records.append(record)

                processed_count += 1

            # Only show file header if there are changes to display
            if file_changes > 0:
                print(f"\n{'=' * 70}")
                print(f"PROCESSING: {file_path}")
                print(f"{'=' * 70}")

                # Show all records with changes
                for change_info in records_with_changes:
                    print(
                        f"\n--- Record {change_info['index']}/{len(records)} [NEEDS CLEANING] ---"
                    )
                    print("📝 Changes detected:")
                    print(f"{'=' * 60}")
                    print("ORIGINAL:")
                    print(f'"{change_info["original"]}"')
                    print("\nCLEANED:")
                    print(f'"{change_info["cleaned"]}"')
                    print(f"{'=' * 60}")

                print(f"\n{'=' * 70}")
                if args.preview:
                    print(
                        f"📋 WOULD CLEAN {file_changes}/{processed_count} records in {os.path.basename(file_path)}"
                    )
                else:
                    print(
                        f"✅ CLEANED {file_changes}/{processed_count} records in {os.path.basename(file_path)}"
                    )

            # Save the file if changes were made (non-preview mode)
            if not args.preview and file_changes > 0:
                save_json_file(file_path, updated_records)

            total_files += 1
            total_records += processed_count

        except Exception as e:
            print(f"❌ Error processing {file_path}: {e}")

    print(f"\n{'=' * 70}")
    print("📊 SUMMARY")
    print(f"{'=' * 70}")
    print(f"Files processed: {total_files}")
    print(f"Total records: {total_records}")
    print(f"Records cleaned: {total_cleaned}")

    if args.preview and total_cleaned > 0:
        print("\n💡 Run without --preview to apply changes")
    elif total_cleaned > 0:
        print("✨ Cleanup complete!")
    elif args.preview:
        print("✨ All files are already clean!")
    else:
        print("✨ No changes needed!")


if __name__ == "__main__":
    main()
