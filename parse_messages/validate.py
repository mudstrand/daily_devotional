#!/usr/bin/env python3
import json
import sys
from typing import Any, Dict, Iterable

EXPECTED = {
    "found_verse": True,
    "found_reflection": True,
    "found_prayer": True,
    "found_reading": False,
}


def iter_records(obj: Any) -> Iterable[Dict[str, Any]]:
    """
    Yield record-like dicts from the loaded JSON.
    Handles:
      - a list of records
      - an object with an 'attachments' array containing items with 'content' (list)
      - an object with a top-level 'content' list
    """
    if isinstance(obj, list):
        for rec in obj:
            if isinstance(rec, dict):
                yield rec
        return

    if isinstance(obj, dict):
        # Direct content list
        if isinstance(obj.get("content"), list):
            for rec in obj["content"]:
                if isinstance(rec, dict):
                    yield rec

        # Attachments shape (like from the example)
        attachments = obj.get("attachments")
        if isinstance(attachments, list):
            for att in attachments:
                if isinstance(att, dict) and isinstance(att.get("content"), list):
                    for rec in att["content"]:
                        if isinstance(rec, dict):
                            yield rec
        return


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: vslidate.py <path-to-json-file>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading/parsing JSON: {e}", file=sys.stderr)
        sys.exit(2)

    mismatched_ids = []

    for rec in iter_records(data):
        msg_id = rec.get("message_id")
        # Only consider records that have all four keys; skip others silently
        has_all = all(k in rec for k in EXPECTED.keys())
        if not has_all:
            continue

        values = {
            "found_verse": bool(rec.get("found_verse")),
            "found_reflection": bool(rec.get("found_reflection")),
            "found_prayer": bool(rec.get("found_prayer")),
            "found_reading": bool(rec.get("found_reading")),
        }

        if values != EXPECTED:
            # Print message_id when provided; otherwise print a placeholder
            mismatched_ids.append(
                msg_id if msg_id is not None else "<missing message_id>"
            )

    # Output one per line as requested
    for mid in mismatched_ids:
        print(mid)


if __name__ == "__main__":
    main()
