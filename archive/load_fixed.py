#!/usr/bin/env python3
import os
import re
import argparse
from typing import Dict

import database

FIXED_DIR = "fixed"
LOADED_SUFFIX = ".loaded"
SEP_LINE = "==================================================================="

SECTION_ORDER = [
    "message-id",
    "date_utc",
    "subject",
    "verse",
    "reflection",
    "prayer",
    "body_text",  # optional
    "raw_body",
]


def parse_fixed_file(path: str) -> Dict[str, str]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    values: Dict[str, str] = {k: "" for k in SECTION_ORDER}

    # message-id on first line
    m = re.match(r"(?i)^message-id:\s*(.+?)\s*\r?\n", content)
    if not m:
        raise ValueError(f"{os.path.basename(path)}: missing 'message-id:' header")
    values["message-id"] = m.group(1).strip()

    rest = content[m.end() :]

    def block(name: str, text: str) -> str:
        # Match "<name>:\n\n<content>\n==================================================================="
        # Accept 0–2 blank lines after header; capture everything lazily up to separator
        pat = re.compile(
            rf"(?is)^[ \t]*{re.escape(name)}[ \t]*:\s*\r?\n(?:\r?\n)?(.*?)\r?\n{re.escape(SEP_LINE)}\s*",
            flags=re.MULTILINE,
        )
        mm = pat.search(text)
        return mm.group(1).strip() if mm else ""

    values["date_utc"] = block("date_utc", rest)
    values["subject"] = block("subject", rest)
    values["verse"] = block("verse", rest)
    values["reflection"] = block("reflection", rest)
    values["prayer"] = block("prayer", rest)
    values["body_text"] = block("body_text", rest)  # may be empty/absent
    values["raw_body"] = block("raw_body", rest)

    return values


def build_args():
    p = argparse.ArgumentParser(
        description="Load fixed devotional files into the database (fully populated)."
    )
    p.add_argument("--dir", default=FIXED_DIR, help="Directory containing fixed files.")
    p.add_argument(
        "--dry-run", action="store_true", help="Do not write to DB or rename files."
    )
    p.add_argument(
        "--sender",
        default="pastor.sather5@gmail.com",
        help="Sender email to store with records.",
    )
    p.add_argument(
        "--show",
        action="store_true",
        help="Show parsed lengths for verse/reflection/prayer before upsert.",
    )
    return p.parse_args()


def none_if_blank(s: str) -> str | None:
    s = (s or "").strip()
    return s if s else None


def main():
    args = build_args()
    database.init_db()

    if not os.path.isdir(args.dir):
        print(f"No such directory: {args.dir}")
        return

    files = [f for f in os.listdir(args.dir) if f.lower().endswith(".txt")]
    if not files:
        print("No .txt files found to load.")
        return

    loaded = 0
    skipped = 0
    for fname in files:
        in_path = os.path.join(args.dir, fname)
        try:
            rec = parse_fixed_file(in_path)
            mid = rec["message-id"]
            if not mid:
                raise ValueError("message-id is required")

            date_utc = none_if_blank(rec.get("date_utc"))
            subject = none_if_blank(rec.get("subject"))
            verse = none_if_blank(rec.get("verse"))
            reflection = none_if_blank(rec.get("reflection"))
            prayer = none_if_blank(rec.get("prayer"))
            body_text = rec.get("body_text", "")
            raw_body = rec.get("raw_body", "")

            if args.show:
                print(
                    f"{fname} | mid={mid} | subj_len={len(subject or '')} verse_len={len(verse or '')} refl_len={len(reflection or '')} prayer_len={len(prayer or '')}"
                )

            payload = {
                "message_id": mid,
                "date": date_utc,
                "subject": subject,
                "verse": verse,
                "reflection": reflection,
                "prayer": prayer,
                "identified": True,
            }

            if args.dry_run:
                print(f"DRY RUN: would upsert {mid}")
            else:
                # Main upsert
                database.upsert_devotional(
                    payload,
                    sender=args.sender,
                    save_raw_html=False,
                    save_normalized_text=False,
                )
                # Optionally store raw/normalized text if provided
                if raw_body.strip() or body_text.strip():
                    with database.get_conn() as conn:
                        if raw_body.strip():
                            conn.execute(
                                "UPDATE devotionals SET raw_html = ? WHERE message_id = ?",
                                (raw_body, mid),
                            )
                        if body_text.strip():
                            conn.execute(
                                "UPDATE devotionals SET normalized_text = ? WHERE message_id = ?",
                                (body_text, mid),
                            )
                # Rename to prevent reloading
                os.replace(in_path, in_path + LOADED_SUFFIX)

            loaded += 1
            print(f"LOADED {mid} from {fname}")
        except Exception as e:
            skipped += 1
            print(f"SKIP {fname}: {e}")

    print(f"Done. Loaded={loaded}, Skipped={skipped}")


if __name__ == "__main__":
    main()
