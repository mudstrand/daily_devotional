#!/usr/bin/env python3
import argparse
import glob
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

Record = Dict[str, Any]


def try_parse_iso(s: str) -> Optional[datetime]:
    """
    Try parsing ISO-8601 variants using only stdlib:
    - 2021-10-22T21:24:26+00:00
    - 2021-10-22T21:24:26Z
    - 2021-10-22 21:24:26+00:00
    """
    ss = s.strip()
    ss = ss.replace("Z", "+00:00")  # fromisoformat doesn't accept 'Z'
    try:
        return datetime.fromisoformat(ss)
    except Exception:
        # Try replacing space ' ' with 'T' if needed
        if " " in ss and "T" not in ss:
            try:
                return datetime.fromisoformat(ss.replace(" ", "T"))
            except Exception:
                pass
    return None


def try_parse_rfc2822(s: str) -> Optional[datetime]:
    """
    Parse RFC 2822 / email-style dates:
    Example: Tue, 16 Jul 2019 19:05:51 -0500
    """
    try:
        dt = parsedate_to_datetime(s)
        return dt
    except Exception:
        return None


def try_parse_common_patterns(s: str) -> Optional[datetime]:
    """
    A few extra common patterns without timezone letters.
    """
    patterns = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in patterns:
        try:
            return datetime.strptime(s[: len(fmt)], fmt).replace(tzinfo=None)
        except Exception:
            continue
    return None


def parse_to_yyyy_mm_dd(value: Any) -> Optional[str]:
    """
    Parse many common UTC/offset datetime formats and return YYYY-MM-DD.
    Does not convert timezones to UTC before extracting date; it uses the local
    calendar date implied by the timestamp and its offset. For your use case,
    this matches the common expectation for stored timestamps.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Fast path: if it already looks like YYYY-MM-DD at the start, validate and return
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        ymd = s[:10]
        try:
            datetime.strptime(ymd, "%Y-%m-%d")
            return ymd
        except Exception:
            pass

    # ISO attempts
    dt = try_parse_iso(s)
    if dt is not None:
        return dt.date().isoformat()

    # RFC 2822 attempts
    dt = try_parse_rfc2822(s)
    if dt is not None:
        return dt.date().isoformat()

    # Common patterns without offset
    dt = try_parse_common_patterns(s)
    if dt is not None:
        return dt.date().isoformat()

    # Last-resort: if first 10 chars look like YYYY-MM-DD, return them
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]

    return None


def load_records(path: Path) -> Optional[Union[Record, List[Record]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"[WARN] Skipping invalid JSON: {path} ({e})")
        return None


def write_records(path: Path, data: Union[Record, List[Record]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    bak = path.with_suffix(path.suffix + ".bak")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if not bak.exists():
        path.replace(bak)
    else:
        path.unlink(missing_ok=True)
    tmp.replace(path)


def process_file(path: Path, preview: bool) -> int:
    data = load_records(path)
    if data is None:
        return 0

    if isinstance(data, dict):
        recs = [data]
        is_list = False
    elif isinstance(data, list):
        recs = [r for r in data if isinstance(r, dict)]
        is_list = True
    else:
        print(f"[WARN] Unsupported JSON structure in {path}; expected object or list.")
        return 0

    updates = 0
    changes: List[str] = []

    for idx, rec in enumerate(recs):
        raw = rec.get("date_utc")
        ymd = parse_to_yyyy_mm_dd(raw)
        if ymd:
            old = rec.get("msg_date")
            if old != ymd:
                updates += 1
                if preview:
                    changes.append(f"  record[{idx}]: msg_date {old!r} -> {ymd!r}")
                else:
                    rec["msg_date"] = ymd
        else:
            if preview:
                changes.append(f"  record[{idx}]: could not parse date_utc {raw!r}")
            else:
                if "msg_date" in rec:
                    del rec["msg_date"]
                print(f"[WARN] Could not parse date_utc to msg_date in {path}: {raw!r}")

    if preview:
        if updates > 0 or changes:
            print(f"[PREVIEW] {path}: {updates} update(s)")
            for line in changes:
                print(line)
    else:
        if updates > 0:
            out = recs if is_list else recs[0]
            write_records(path, out)

    return updates


def expand_globs(patterns: List[str]) -> List[Path]:
    files: List[str] = []
    for pat in patterns:
        files.extend(glob.glob(pat, recursive=True))
    paths: List[Path] = []
    seen = set()
    for f in files:
        p = Path(f)
        if p.is_file() and p.suffix.lower() == ".json":
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser(
        description="Normalize date_utc to msg_date (YYYY-MM-DD) in JSON files."
    )
    ap.add_argument(
        "--preview",
        action="store_true",
        help="Show what would change without writing files",
    )
    ap.add_argument(
        "globs",
        nargs="+",
        help="Glob patterns, e.g., './data/*.json' './data/**/*.json'",
    )
    args = ap.parse_args()

    paths = expand_globs(args.globs)
    if not paths:
        print("No JSON files matched the given patterns.")
        return

    total_files = 0
    total_updates = 0
    for path in paths:
        total_files += 1
        total_updates += process_file(path, preview=args.preview)

    if args.preview:
        print(
            f"Preview complete. Files examined: {total_files}, records needing update: {total_updates}"
        )
    else:
        print(
            f"Completed. Files processed: {total_files}, records updated: {total_updates}"
        )


if __name__ == "__main__":
    main()
