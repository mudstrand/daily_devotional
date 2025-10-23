#!/usr/bin/env python3
from pathlib import Path

complete_path = Path("complete_pastor_al.ids")
sqlite_path = Path("sqlite_message_ids.txt")
out_path = Path("missing_from_sqlite.ids")


def read_ids(p: Path) -> set[str]:
    return {
        ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()
    }


complete_ids = read_ids(complete_path)
sqlite_ids = read_ids(sqlite_path)

missing = sorted(complete_ids - sqlite_ids)  # sort optional
out_path.write_text("\n".join(missing) + "\n", encoding="utf-8")

print(f"Complete: {len(complete_ids)}")
print(f"SQLite:   {len(sqlite_ids)}")
print(f"Missing:  {len(missing)} -> {out_path}")
