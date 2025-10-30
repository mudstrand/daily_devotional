#!/usr/bin/env python3
import json
import sys
import argparse
from typing import Any, Dict, Iterable, Tuple, List, Union

EXPECTED = {
    "found_verse": True,
    "found_reflection": True,
    "found_prayer": True,
    "found_reading": False,
}


def iter_records(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, list):
        for rec in obj:
            if isinstance(rec, dict):
                yield rec
        return
    if isinstance(obj, dict):
        if isinstance(obj.get("content"), list):
            for rec in obj["content"]:
                if isinstance(rec, dict):
                    yield rec
        attachments = obj.get("attachments")
        if isinstance(attachments, list):
            for att in attachments:
                if isinstance(att, dict) and isinstance(att.get("content"), list):
                    for rec in att["content"]:
                        if isinstance(rec, dict):
                            yield rec
        return


def delete_by_message_id(obj: Any, target_id: str) -> Tuple[Any, int]:
    deleted = 0
    if isinstance(obj, list):
        before = len(obj)
        obj = [
            rec
            for rec in obj
            if not (isinstance(rec, dict) and rec.get("message_id") == target_id)
        ]
        deleted = before - len(obj)
        return obj, deleted
    if isinstance(obj, dict):
        if isinstance(obj.get("content"), list):
            before = len(obj["content"])
            obj["content"] = [
                rec
                for rec in obj["content"]
                if not (isinstance(rec, dict) and rec.get("message_id") == target_id)
            ]
            deleted += before - len(obj["content"])
        attachments = obj.get("attachments")
        if isinstance(attachments, list):
            for att in attachments:
                if isinstance(att, dict) and isinstance(att.get("content"), list):
                    before = len(att["content"])
                    att["content"] = [
                        rec
                        for rec in att["content"]
                        if not (
                            isinstance(rec, dict) and rec.get("message_id") == target_id
                        )
                    ]
                    deleted += before - len(att["content"])
    return obj, deleted


def clean_string(s: str) -> str:
    # Apply replacements in the exact order:
    # 1) ". . . " -> ". "
    s = s.replace(". . . ", ". ")
    # 2) ". . ." -> "."
    s = s.replace(". . .", ".")
    # 3) ". \"" -> ".\""
    s = s.replace('. "', '."')
    return s


def clean_obj(obj: Any) -> Any:
    # Recursively traverse and clean all string values
    if isinstance(obj, str):
        return clean_string(obj)
    if isinstance(obj, list):
        return [clean_obj(item) for item in obj]
    if isinstance(obj, dict):
        return {k: clean_obj(v) for k, v in obj.items()}
    return obj


def parse_args() -> Tuple[str, Union[str, None], bool]:
    parser = argparse.ArgumentParser(
        prog=sys.argv[0],
        description="Validate parsed JSON and optionally delete one record by message_id or clean text.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "-d",
        "--delete",
        metavar="message_id",
        help="Single message_id to delete",
    )
    parser.add_argument(
        "-c",
        "--clean",
        action="store_true",
        help="Clean up text by applying specific search-and-replace steps",
    )
    parser.add_argument("path", help="path to JSON file")
    args = parser.parse_args()
    return args.path, args.delete, args.clean


def main() -> None:
    path, delete_id, do_clean = parse_args()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading/parsing JSON: {e}", file=sys.stderr)
        sys.exit(2)

    modified = False

    if delete_id:
        data, removed = delete_by_message_id(data, delete_id)
        if removed == 0:
            print(
                "Warning: no records found for provided message_id; file unchanged.",
                file=sys.stderr,
            )
        else:
            modified = True
            print(f"Deleted {removed} record(s)")

    if do_clean:
        cleaned = clean_obj(data)
        if cleaned != data:
            data = cleaned
            modified = True
            print("Applied cleanup replacements")
        else:
            print("Cleanup found nothing to change")

    if modified:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"Updated {path}")
        except Exception as e:
            print(f"Error writing updated JSON: {e}", file=sys.stderr)
            sys.exit(3)

    mismatched: List[Tuple[str, str]] = []
    for rec in iter_records(data):
        if not all(k in rec for k in EXPECTED.keys()):
            continue
        values = {
            "found_verse": bool(rec.get("found_verse")),
            "found_reflection": bool(rec.get("found_reflection")),
            "found_prayer": bool(rec.get("found_prayer")),
            "found_reading": bool(rec.get("found_reading")),
        }
        if values != EXPECTED:
            msg_id = rec.get("message_id", "<missing message_id>")
            subject = rec.get("subject", "")
            mismatched.append((msg_id, subject))

    for mid, subj in mismatched:
        print(f"{mid}  {subj}")


if __name__ == "__main__":
    main()
