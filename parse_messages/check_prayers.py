#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Tuple, List, Union, Optional

# ---------- Helpers to walk JSON ----------


def iter_prayer_entries(
    obj: Any,
    path: List[Union[str, int]] = None,
    ancestor_message_id: Optional[str] = None,
) -> Iterable[Tuple[List[Union[str, int]], str, Optional[str]]]:
    """
    Yield (path, prayer_value, message_id) for every 'prayer' key whose value is a string.
    Tracks the nearest ancestor 'message_id' string encountered along the path.
    """
    if path is None:
        path = []

    if isinstance(obj, dict):
        current_msg_id = ancestor_message_id
        mid_val = obj.get("message_id")
        if isinstance(mid_val, str):
            current_msg_id = mid_val

        if "prayer" in obj and isinstance(obj["prayer"], str):
            yield (path + ["prayer"], obj["prayer"], current_msg_id)

        for k, v in obj.items():
            yield from iter_prayer_entries(v, path + [k], current_msg_id)

    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_prayer_entries(v, path + [i], ancestor_message_id)


def ends_with_amen(text: str) -> bool:
    """
    True if text ends with 'Amen' or 'Amen.' (ignoring trailing whitespace).
    """
    if not isinstance(text, str):
        return False
    s = text.rstrip()
    return s.endswith("Amen") or s.endswith("Amen.")


def safe_preview(text: str, max_len: int = 120) -> str:
    if not isinstance(text, str):
        return repr(text)
    t = text.replace("\n", "\\n")
    return t if len(t) <= max_len else t[: max_len - 3] + "..."


def locate_line_number(json_text: str, value: str) -> Optional[int]:
    """
    Best-effort line number guess: find the first line that contains both "prayer"
    and a short non-empty snippet of the value. Works best on pretty-printed JSON.
    """
    lines = json_text.splitlines()
    needle_key = '"prayer"'

    snippet = ""
    if isinstance(value, str):
        for part in value.splitlines():
            if part.strip():
                snippet = part[:60]
                break

    if snippet:
        for idx, line in enumerate(lines, start=1):
            if needle_key in line and snippet in line:
                return idx

    for idx, line in enumerate(lines, start=1):
        if needle_key in line:
            return idx
    return None


# ---------- Per-file processing ----------


def process_file(path: Path) -> int:
    """
    Returns number of violations in this file.
    """
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except Exception as e:
        print(f"[ERROR] {path}: cannot read/parse JSON: {e}", file=sys.stderr)
        return 0

    violations = 0
    for _, val, msg_id in iter_prayer_entries(data):
        # Skip empty-string prayers (after trimming whitespace)
        if isinstance(val, str) and val.strip() == "":
            continue

        if not ends_with_amen(val):
            violations += 1
            ln = locate_line_number(text, val)
            loc = f"{path}:{ln}" if ln else f"{path}"
            mid = msg_id if msg_id is not None else "<no message_id found>"
            print(f"[VIOLATION] {loc} — message_id={mid}")
            print(f"    Value: {safe_preview(val)!r}")
    return violations


# ---------- CLI ----------


def main():
    ap = argparse.ArgumentParser(
        description="Read-only check: verify all non-empty 'prayer' values in JSON end with Amen or Amen. Reports filename and message_id."
    )
    ap.add_argument(
        "paths",
        nargs="+",
        help="One or more files or directories to scan",
    )
    ap.add_argument(
        "-e",
        "--ext",
        default=".json",
        help="File extension filter for directories (default: .json)",
    )
    ap.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recurse into subdirectories for directories provided",
    )
    args = ap.parse_args()

    files: List[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if not p.exists():
            print(f"[ERROR] Path not found: {p}", file=sys.stderr)
            continue
        if p.is_file():
            files.append(p)
        else:
            if args.recursive:
                files.extend([f for f in p.rglob(f"*{args.ext}") if f.is_file()])
            else:
                files.extend([f for f in p.glob(f"*{args.ext}") if f.is_file()])

    files = sorted(set(files))

    if not files:
        print("[ERROR] No files to process.", file=sys.stderr)
        sys.exit(2)

    total_files = 0
    total_violations = 0
    for f in files:
        total_files += 1
        total_violations += process_file(f)

    print(f"\nSummary: scanned {total_files} file(s); violations={total_violations}")
    sys.exit(1 if total_violations else 0)


if __name__ == "__main__":
    main()
