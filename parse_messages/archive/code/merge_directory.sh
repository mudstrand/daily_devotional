#!/usr/bin/env python3
import json
from pathlib import Path

DIR_A = Path("orig_database_content")
DIR_B = Path("loadable")
OUT_DIR = Path("merged_out")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def dedup_list(lst):
    seen, out = set(), []
    for item in lst:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out

def deepmerge(a, b):
    # dict + dict: recursive merge, arrays concat+unique, scalars: b overrides a
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = deepmerge(out[k], v) if k in out else v
        return out
    if isinstance(a, list) and isinstance(b, list):
        return dedup_list(a + b)
    return b  # fallback: right side wins

def read_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None

files_a = {p.name for p in DIR_A.iterdir() if p.is_file()}
files_b = {p.name for p in DIR_B.iterdir() if p.is_file()}

common = sorted(files_a & files_b)
only_a = sorted(files_a - files_b)
only_b = sorted(files_b - files_a)

# Copy uniques
for name in only_a:
    (OUT_DIR / name).write_bytes((DIR_A / name).read_bytes())
for name in only_b:
    (OUT_DIR / name).write_bytes((DIR_B / name).read_bytes())

# Merge commons
for name in common:
    pa, pb = DIR_A / name, DIR_B / name
    a, b = read_json(pa), read_json(pb)

    # If both parse as JSON, merge with sensible rules
    if a is not None and b is not None:
        if isinstance(a, list) and isinstance(b, list):
            merged = dedup_list(a + b)
        elif isinstance(a, dict) and isinstance(b, dict):
            merged = deepmerge(a, b)
        else:
            # Different shapes: keep both under namespaced keys
            merged = {"from_a": a, "from_b": b}
        (OUT_DIR / name).write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    else:
        # If any side isn't valid JSON, just concatenate bytes (or pick a strategy)
        # Here we prefer keeping both by appending with a newline separator.
        data = pa.read_bytes() + b"\n" + pb.read_bytes()
        (OUT_DIR / name).write_bytes(data)

print(f"Done. Wrote to {OUT_DIR}")
