#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from typing import Dict, Any, Iterable

FIELDS = ('verse', 'reflection', 'prayer')
RAW_NEEDLE = r'\" '  # backslash + quote + space


def iter_json_records(path: Path) -> Iterable[Dict[str, Any]]:
    txt = path.read_text(encoding='utf-8', errors='replace')
    s = txt.strip()
    if not s:
        return
    # Try single JSON value (array or object)
    try:
        data = json.loads(s)
        if isinstance(data, list):
            for rec in data:
                if isinstance(rec, dict):
                    yield rec
            return
        elif isinstance(data, dict):
            yield data
            return
    except json.JSONDecodeError:
        pass
    # NDJSON fallback
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
            if isinstance(rec, dict):
                yield rec
        except json.JSONDecodeError:
            continue


def contains_raw_escaped_quote_space(raw_value: str) -> bool:
    # raw_value is the JSON-encoded string value including quotes.
    # Example: "Paul says: \" Some ..."
    # We simply check inside the quotes whether the raw sequence \"  (then space) occurs.
    if len(raw_value) >= 2 and raw_value[0] == '"' and raw_value[-1] == '"':
        inner = raw_value[1:-1]
    else:
        inner = raw_value
    return RAW_NEEDLE in inner


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    files = sorted(base.glob('parsed_*.json'))
    if not files:
        print('No files matching parsed_*.json found', file=sys.stderr)
        sys.exit(1)

    total = 0
    for fp in files:
        txt = fp.read_text(encoding='utf-8', errors='replace')
        # Build message_id -> record map (parsed) and also raw string map (raw JSON slices)
        # We do a light-weight raw scan to extract each field’s JSON text.
        # Regex-free approach: parse once and re-encode values exactly like json.dumps to compare.
        try:
            data = json.loads(txt.strip())
            records = data if isinstance(data, list) else [data]
        except Exception:
            # NDJSON
            records = []
            for ln in txt.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                    if isinstance(rec, dict):
                        records.append(rec)
                except Exception:
                    continue

        for rec in records:
            if not isinstance(rec, dict):
                continue
            msg_id = rec.get('message_id', '')
            for field in FIELDS:
                val = rec.get(field, '')
                if not isinstance(val, str):
                    continue
                # Obtain the raw JSON string for this value via json.dumps, which uses \" to escape quotes.
                raw_string = json.dumps(val, ensure_ascii=False)
                if contains_raw_escaped_quote_space(raw_string):
                    total += 1
                    print(f'{fp.name} | {msg_id} | {field}')
                    print(val)
                    print('-' * 80)

    if total == 0:
        print('No matches for raw sequence \\"  (backslash + quote + space) in verse/reflection/prayer')


if __name__ == '__main__':
    main()
