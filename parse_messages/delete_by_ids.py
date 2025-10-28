#!/usr/bin/env python3
import argparse
import json
import sys
from typing import Any, Dict, Iterable, List, Tuple


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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="delete_by_ids.py",
        description="Delete records from a JSON file by message_id list (one ID per line).",
        allow_abbrev=False,
    )
    p.add_argument(
        "json_path",
        help="Path to JSON file containing records (list or object with content/attachments)",
    )
    p.add_argument(
        "ids_path",
        help="Path to text file with one message_id per line",
    )
    p.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Do not write changes; just report what would be deleted",
    )
    return p.parse_args()


def load_ids(ids_path: str) -> List[str]:
    ids: List[str] = []
    try:
        with open(ids_path, "r", encoding="utf-8") as f:
            for line in f:
                mid = line.strip()
                if mid and not mid.startswith("#"):
                    ids.append(mid)
    except Exception as e:
        print(f"Error reading IDs file: {e}", file=sys.stderr)
        sys.exit(2)
    return ids


def main() -> None:
    args = parse_args()
    ids = load_ids(args.ids_path)
    if not ids:
        print(
            "No message_ids to delete (file empty or only comments).", file=sys.stderr
        )
        sys.exit(0)

    try:
        with open(args.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading/parsing JSON: {e}", file=sys.stderr)
        sys.exit(2)

    total_deleted = 0
    per_id_deleted: List[Tuple[str, int]] = []
    for mid in ids:
        data, removed = delete_by_message_id(data, mid)
        per_id_deleted.append((mid, removed))
        total_deleted += removed

    # Report
    for mid, removed in per_id_deleted:
        if removed == 0:
            print(f"{mid}: not found")
        else:
            print(f"{mid}: deleted {removed} record(s)")

    print(f"Total deleted: {total_deleted}")

    if args.dry_run:
        print("Dry-run: no changes written.")
        return

    if total_deleted > 0:
        try:
            with open(args.json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"Updated {args.json_path}")
        except Exception as e:
            print(f"Error writing updated JSON: {e}", file=sys.stderr)
            sys.exit(3)


if __name__ == "__main__":
    main()
