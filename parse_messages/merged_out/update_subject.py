#!/usr/bin/env python3
import argparse
import json
import sys
from typing import Any, Union

TARGET_VALUE = "thoughts to live by"


def update_subject(obj: Any, value: str) -> Any:
    """
    Recursively set 'subject' in dicts (and lists of dicts) to the given value.
    Leaves other fields unchanged.
    """
    if isinstance(obj, dict):
        # Only set if key exists; comment next line if you want to force-add when missing
        if "subject" in obj:
            obj["subject"] = value
        # Recurse into nested structures in case there are embedded records
        for k, v in obj.items():
            obj[k] = update_subject(v, value)
        return obj
    elif isinstance(obj, list):
        return [update_subject(item, value) for item in obj]
    else:
        return obj


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Replace all "subject" values with a fixed string in a JSON file.'
    )
    parser.add_argument("filename", help="Path to the JSON file to modify")
    parser.add_argument(
        "--value",
        default=TARGET_VALUE,
        help=f'New value for "subject" (default: "{TARGET_VALUE}")',
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Write changes back to the same file (otherwise prints to stdout)",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Indent for pretty output (default: 2). Use 0 for compact.",
    )
    args = parser.parse_args()

    try:
        with open(args.filename, "r", encoding="utf-8") as f:
            data: Union[dict, list] = json.load(f)
    except FileNotFoundError:
        print(f"Error: file not found: {args.filename}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {args.filename}: {e}", file=sys.stderr)
        sys.exit(1)

    updated = update_subject(data, args.value)

    if args.in_place:
        with open(args.filename, "w", encoding="utf-8") as f:
            if args.indent > 0:
                json.dump(updated, f, ensure_ascii=False, indent=args.indent)
                f.write("\n")
            else:
                json.dump(updated, f, ensure_ascii=False, separators=(",", ":"))
        print(f'Updated "{args.filename}"')
    else:
        if args.indent > 0:
            json.dump(updated, sys.stdout, ensure_ascii=False, indent=args.indent)
            sys.stdout.write("\n")
        else:
            json.dump(updated, sys.stdout, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
