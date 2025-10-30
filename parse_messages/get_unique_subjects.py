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
    Goes through all the json data in the loadable directory and pulls out all the unique values for "subject"
    and their locations.
    """
    subject_locations = defaultdict(list)
    for filename in os.listdir("loadable"):
        if filename.endswith(".json"):
            filepath = os.path.join("loadable", filename)
            with open(filepath, "r") as f:
                try:
                    content = f.read()
                    data = json.loads(content)
                    lines = content.splitlines()
                    if isinstance(data, list):
                        for item in data:
                            if "subject" in item:
                                for i, line in enumerate(lines):
                                    if f'"subject": "{item["subject"]}"' in line:
                                        subject_locations[item["subject"]].append(
                                            {"filepath": filepath, "line": i + 1}
                                        )
                                        break
                    elif isinstance(data, dict):
                        if "subject" in data:
                            for i, line in enumerate(lines):
                                if f'"subject": "{data["subject"]}"' in line:
                                    subject_locations[data["subject"]].append(
                                        {"filepath": filepath, "line": i + 1}
                                    )
                                    break
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
    return subject_locations


if __name__ == "__main__":
    subject_locations = get_subject_locations()

    normalized_subjects = defaultdict(list)
    for subject, locations in subject_locations.items():
        normalized = normalize_subject(subject)
        normalized_subjects[normalized].append((subject, locations))

    for normalized, subject_group in sorted(normalized_subjects.items()):
        if len(subject_group) == 1 and len(subject_group[0][1]) == 1:
            # Only one subject in the group, and it appears only once
            subject, locations = subject_group[0]
            location = locations[0]
            print(f"{subject}: code -g {location['filepath']}:{location['line']}")
        else:
            print(f"--- Group: {normalized} ---")
            total_count = 0
            for subject, locations in subject_group:
                total_count += len(locations)
                print(f"  {subject}: {len(locations)}")
            print(f"  Total count: {total_count}")
