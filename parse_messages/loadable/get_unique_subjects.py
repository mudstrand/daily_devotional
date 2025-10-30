#!/usr/bin/env python3

import json
import os
import re
from collections import defaultdict


def normalize_subject(subject):
    """Lowercase and remove non-alphanumeric characters from a string."""
    return re.sub(r"[^a-z0-9]", "", subject.lower())


def get_subject_locations():
    """
    Scan all JSON files in the same directory as this script, collect unique
    'subject' values and their file/line locations.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))

    subject_locations = defaultdict(list)
    try:
        entries = os.listdir(script_dir)
    except FileNotFoundError:
        return subject_locations

    for filename in entries:
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(script_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            continue

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            continue

        lines = content.splitlines()

        def record(subject_value: str):
            # Find the first line containing the exact JSON snippet for subject
            needle = f'"subject": "{subject_value}"'
            for i, line in enumerate(lines, start=1):
                if needle in line:
                    subject_locations[subject_value].append(
                        {"filepath": filename, "line": i}
                    )
                    return
            # Fallback: if not found by exact snippet, try a looser match on the line
            for i, line in enumerate(lines, start=1):
                if '"subject"' in line and subject_value in line:
                    subject_locations[subject_value].append(
                        {"filepath": filename, "line": i}
                    )
                    return

        if isinstance(data, list):
            for item in data:
                if (
                    isinstance(item, dict)
                    and "subject" in item
                    and isinstance(item["subject"], str)
                ):
                    record(item["subject"])
        elif isinstance(data, dict):
            if "subject" in data and isinstance(data["subject"], str):
                record(data["subject"])

    return subject_locations


if __name__ == "__main__":
    subject_locations = get_subject_locations()

    normalized_subjects = defaultdict(list)
    for subject, locations in subject_locations.items():
        normalized = normalize_subject(subject)
        normalized_subjects[normalized].append((subject, locations))

    for normalized, subject_group in sorted(normalized_subjects.items()):
        # Simple case: only one subject and it appears once
        if len(subject_group) == 1 and len(subject_group[0][1]) == 1:
            subject, locations = subject_group[0]
            location = locations[0]
            print(f"{subject}: code -g {location['filepath']}:{location['line']}")
            continue

        # Grouped case
        print(f"--- Group: {normalized} ---")
        total_count = sum(len(locations) for _, locations in subject_group)

        if total_count < 10:
            # List every instance with filename:line
            for subject, locations in subject_group:
                for loc in locations:
                    print(f"    {subject}: code -g {loc['filepath']}:{loc['line']}")
            print(f"    Total count: {total_count}")
        else:
            # Too many to list: show counts per subject and total
            for subject, locations in subject_group:
                print(f"    {subject}: {len(locations)}")
            print(f"    Total count: {total_count}")
