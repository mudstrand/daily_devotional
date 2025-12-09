#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SEPARATOR = '=' * 50

# Fields required by the current standard (alphabetical)
# Note: original_content_flat is optional and therefore not in REQUIRED_FIELDS.
REQUIRED_FIELDS = [
    'ai_prayer',
    'ai_reading',
    'ai_reflection_corrected',
    'ai_subject',
    'ai_verse',
    'date_utc',
    'found_prayer',
    'found_reading',
    'found_reflection',
    'found_verse',
    'message_id',
    'original_content',
    'original_reading',
    'original_reflection_text',
    'original_subject',
    'original_verse',
    'original_verse_source',
    'original_verse_text',
    'prayer',
    'reading',
    'reading_text',
    'reflection',
    'subject',
    'verse',
    'verse_source',
    'verse_text',
]

# Optional fields: preserved if present, not required
OPTIONAL_FIELDS = {
    'original_content_flat',
}

# Fields to drop if present
DROP_FIELDS = {
    'original_reading_text',
    'reading_source',
}

# Map deprecated/misspelled fields to current names
RENAME_MAP = {
    'foundreading': 'found_reading',
    'foundprayer': 'found_prayer',
    'foundreflection': 'found_reflection',
    'foundverse': 'found_verse',
    'originalcontent': 'original_content',
    'dateutc': 'date_utc',
    'messageid': 'message_id',
}

# Defaults for required fields
DEFAULTS: Dict[str, Any] = {
    'ai_prayer': False,
    'ai_reading': False,
    'ai_reflection_corrected': False,
    'ai_subject': False,
    'ai_verse': False,
    'date_utc': '',
    'found_prayer': False,
    'found_reading': False,
    'found_reflection': False,
    'found_verse': False,
    'message_id': '',
    'original_content': '',
    'original_reading': '',
    'original_reflection_text': '',
    'original_subject': '',
    'original_verse': '',
    'original_verse_source': '',
    'original_verse_text': '',
    'prayer': '',
    'reading': '',
    'reading_text': '',
    'reflection': '',
    'subject': '',
    'verse': '',
    'verse_source': '',
    'verse_text': '',
}


def load_records(data: Any, filename: Path) -> Tuple[List[Dict[str, Any]], Any, str]:
    """
    Accepts:
      - top-level list of records
      - top-level dict with exactly one list value
    Returns (records, container, key) to allow write-back.
    """
    if isinstance(data, list):
        return data, None, ''
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            key = list_keys[0]
            return data[key], data, key
        raise ValueError(f'{filename}: expected a list or a dict with a single list of records')
    raise ValueError(f'{filename}: unsupported JSON structure')


def apply_renames_and_drops(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    - Apply RENAME_MAP (old -> new). If both old and new exist, prefer the current (new) and drop the old.
    - Drop DROP_FIELDS.
    """
    out = dict(rec)

    # Apply renames
    for old, new in RENAME_MAP.items():
        if old in out:
            if new not in out:
                out[new] = out[old]
            # Remove the old key regardless
            del out[old]

    # Drop unwanted fields
    for k in list(out.keys()):
        if k in DROP_FIELDS:
            del out[k]

    return out


def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns a record normalized to the schema:
      - renames applied
      - drop fields removed
      - required fields ensured (with defaults)
      - optional fields preserved if present
      - keys sorted alphabetically
    """
    rec = apply_renames_and_drops(rec)

    # Start with required fields defaults
    norm: Dict[str, Any] = {f: DEFAULTS.get(f, '') for f in REQUIRED_FIELDS}

    # Overlay existing required fields
    for f in REQUIRED_FIELDS:
        if f in rec:
            norm[f] = rec[f]

    # Preserve optional fields if present
    for f in OPTIONAL_FIELDS:
        if f in rec:
            norm[f] = rec[f]

    # Sort alphabetically
    return {k: norm[k] for k in sorted(norm.keys())}


def preview_validate(paths: List[Path]) -> int:
    """
    --preview:
      - Apply renames/drops in-memory for validation.
      - For each record, report:
            [MISSING] filename.json:INDEX field
            [EXTRA]   filename.json:INDEX field
        where EXTRA excludes optional fields and dropped fields.
      - Exit non-zero if any issues found, else print [OK].
    """
    expected_required = set(REQUIRED_FIELDS)
    allowed_extra = set(OPTIONAL_FIELDS)  # optional allowed if present
    had_issue = False

    for path in paths:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            records, _, _ = load_records(data, path)
        except Exception as e:
            print(f'[ERROR] {path}: cannot read/parse JSON: {e}')
            had_issue = True
            continue

        for idx, rec in enumerate(records, start=1):
            if not isinstance(rec, dict):
                print(f'[WARN] {path}:{idx} record is not an object; skipping')
                had_issue = True
                continue

            # Apply renames/drops for fair validation
            tmp = apply_renames_and_drops(rec)
            present = set(tmp.keys())

            # Missing: required fields not present
            missing = sorted(list(expected_required - present))
            # Extra: present fields not in required or optional (ignore dropped by earlier step)
            extra = sorted([f for f in present if (f not in expected_required and f not in OPTIONAL_FIELDS)])

            for f in missing:
                print(f'[MISSING] {path}:{idx} {f}')
                had_issue = True
            for f in extra:
                print(f'[EXTRA]   {path}:{idx} {f}')
                had_issue = True

    if had_issue:
        print('\n[FAIL] Field set inconsistencies found. Ensure all records match the required schema.')
        return 2

    print('[OK] All records match the required schema (with optional fields allowed).')
    return 0


def write_unify(paths: List[Path]) -> int:
    """
    Non-preview:
      - Apply renames/drops
      - Ensure required fields (fill defaults)
      - Preserve optional fields
      - Sort keys alphabetically
      - Write back
    """
    exit_code = 0
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            records, container, key = load_records(data, path)
        except Exception as e:
            print(f'[ERROR] {path}: cannot read/parse JSON: {e}')
            exit_code = 2
            continue

        new_records: List[Dict[str, Any]] = []
        changed = 0

        for rec in records:
            if not isinstance(rec, dict):
                new_records.append(rec)
                continue
            nr = normalize_record(rec)
            if nr != rec:
                changed += 1
            new_records.append(nr)

        try:
            out = new_records if container is None else {**container, key: new_records}
            path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'[OK] {path}: normalized {changed}/{len(records)}')
        except Exception as e:
            print(f'[ERROR] {path}: failed to write output: {e}')
            exit_code = 2

    return exit_code


def main():
    parser = argparse.ArgumentParser(
        description='Validate/normalize devotional JSON records: enforce required fields, allow optional fields, rename legacy fields, drop deprecated fields, and sort keys.'
    )
    parser.add_argument('files', nargs='+', help='JSON files (e.g., *.json)')
    parser.add_argument(
        '--preview',
        action='store_true',
        help='Validate only; print missing/extra per record and stop with non-zero if any issue.',
    )
    args = parser.parse_args()

    paths = [Path(x) for x in args.files]
    for p in paths:
        if not p.exists():
            print(f'[ERROR] {p}: not found')
            sys.exit(2)

    if args.preview:
        rc = preview_validate(paths)
    else:
        rc = write_unify(paths)

    sys.exit(rc)


if __name__ == '__main__':
    main()
