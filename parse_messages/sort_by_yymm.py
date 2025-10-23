#!/usr/bin/env python3
import re
import shutil
from pathlib import Path
from email.utils import parsedate_to_datetime

# Configuration (project-root relative)
SOURCE_DIR = Path.cwd() / "missing"  # where your 2600+ .txt files currently live
GLOB_PATTERN = "*.txt"  # pattern for message files
FORCE_OVERWRITE = False  # set True to overwrite if a dest file exists

# Regex to capture the Date header line (case-insensitive), e.g.:
# date      : Fri, 1 Apr 2011 12:20:19 -0500
DATE_LINE_RE = re.compile(r"^date\s*:\s*(.+)$", re.IGNORECASE)


def extract_date_header(text: str) -> str | None:
    """
    Return the raw Date header value from the file, or None if not found.
    """
    for line in text.splitlines():
        m = DATE_LINE_RE.match(line.strip())
        if m:
            return m.group(1).strip()
    return None


def header_to_yymm(header_date: str) -> str | None:
    """
    Parse an RFC-2822-like date string into YYMM (year then month).
    Example: 'Fri, 1 Apr 2011 12:20:19 -0500' -> '1104'
    """
    try:
        dt = parsedate_to_datetime(header_date)
        return f"{dt.year % 100:02d}{dt.month:02d}"
    except Exception:
        return None


def main():
    src = SOURCE_DIR
    if not src.exists():
        print(f"Source directory not found: {src}")
        return

    files = sorted(src.glob(GLOB_PATTERN))
    if not files:
        print(f"No files found in {src} matching pattern '{GLOB_PATTERN}'")
        return

    total = len(files)
    moved = 0
    skipped_no_date = 0
    skipped_parse = 0
    skipped_exists = 0
    errors = 0

    print(f"Scanning {total} files in {src} ...")

    for i, fp in enumerate(files, 1):
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            header_date = extract_date_header(text)
            if not header_date:
                skipped_no_date += 1
                continue

            yymm = header_to_yymm(header_date)
            if not yymm:
                skipped_parse += 1
                continue

            # Destination directory is at project root (next to 'missing')
            dest_dir = Path.cwd() / yymm
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / fp.name

            if dest_path.exists() and not FORCE_OVERWRITE:
                skipped_exists += 1
                continue

            if dest_path.exists() and FORCE_OVERWRITE:
                dest_path.unlink(missing_ok=True)

            shutil.move(str(fp), str(dest_path))
            moved += 1

        except Exception as e:
            errors += 1
            print(f"ERROR processing {fp.name}: {e}")

        if i % 200 == 0 or i == total:
            print(f"Processed {i}/{total} files...")

    print("\nSummary:")
    print(f"- Total files scanned: {total}")
    print(f"- Moved: {moved}")
    print(f"- Skipped (no Date header): {skipped_no_date}")
    print(f"- Skipped (Date parse failed): {skipped_parse}")
    print(f"- Skipped (exists, no overwrite): {skipped_exists}")
    print(f"- Errors: {errors}")
    print(f"YYMM directories created at: {Path.cwd()}")


if __name__ == "__main__":
    main()
