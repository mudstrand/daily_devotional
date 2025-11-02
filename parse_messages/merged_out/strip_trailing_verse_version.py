#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from typing import Any, List

# Trailing version tokens to remove (add more as needed)
VERSION_TAGS = ("NIV", "NLT", "KJV")
# Regex to strip: optional whitespace then one of the tags, at end of string
TRAILING_VER_RE = re.compile(rf"\s+(?:{'|'.join(map(re.escape, VERSION_TAGS))})\s*$")


def strip_trailing_version(s: str) -> str:
    if not isinstance(s, str):
        return s
    return TRAILING_VER_RE.sub("", s)


def process_node(
    node: Any, changes: List[str], file_base: str, path_stack: List[str]
) -> bool:
    changed_any = False
    if isinstance(node, dict):
        for k, v in list(node.items()):
            path_stack.append(k)
            if k == "verse" and isinstance(v, str):
                new_v = strip_trailing_version(v)
                if new_v != v:
                    node[k] = new_v
                    loc = ".".join(path_stack)
                    changes.append(
                        f"{file_base}:{loc}\n    - from: {v}\n    + to:   {new_v}"
                    )
                    changed_any = True
            elif isinstance(v, (dict, list)):
                if process_node(v, changes, file_base, path_stack):
                    changed_any = True
            path_stack.pop()
    elif isinstance(node, list):
        for i, v in enumerate(node):
            path_stack.append(f"[{i}]")
            if isinstance(v, (dict, list)):
                if process_node(v, changes, file_base, path_stack):
                    changed_any = True
            path_stack.pop()
    return changed_any


def backup_path(path: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{path}.bak.{ts}"


def process_file(path: str, preview: bool = False, no_backup: bool = False) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        return f"[ERROR] Read failed {path}: {e}"

    base = os.path.basename(path)
    changes: List[str] = []
    changed = process_node(doc, changes, base, [])

    if not changed:
        return f"[SKIP] No verse changes: {path}"

    if preview:
        header = f"[PREVIEW] {path} — {len(changes)} change(s)"
        return header + ("\n" + "\n".join(changes) if changes else "")

    try:
        if not no_backup:
            bp = backup_path(path)
            with open(bp, "w", encoding="utf-8") as bf:
                json.dump(doc, bf, ensure_ascii=False, indent=2)
                bf.write("\n")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return f"[OK] Updated {path} ({len(changes)} change(s))"
    except Exception as e:
        return f"[ERROR] Write failed {path}: {e}"


def find_json_files(paths: List[str]) -> List[str]:
    files: List[str] = []
    paths = paths or ["."]
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in names:
                    if n.lower().endswith(".json"):
                        files.append(os.path.join(root, n))
        elif p.lower().endswith(".json") and os.path.isfile(p):
            files.append(p)
    return sorted(files)


def main():
    ap = argparse.ArgumentParser(
        description='Remove trailing version tags (e.g., "NIV", "NLT") from JSON "verse" fields.'
    )
    ap.add_argument(
        "paths", nargs="*", help="Files or directories (default: current directory)"
    )
    ap.add_argument(
        "--preview",
        action="store_true",
        help="Show proposed changes without writing files",
    )
    ap.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create .bak timestamped backups",
    )
    args = ap.parse_args()

    files = find_json_files(args.paths)
    if not files:
        print("[INFO] No JSON files found.", file=sys.stderr)
        sys.exit(1)

    for fp in files:
        print(process_file(fp, preview=args.preview, no_backup=args.no_backup))


if __name__ == "__main__":
    main()
