#!/usr/bin/env python3
"""
post_devotional.py

Reads one devotional from the SQLite database and posts it via telegram_poster.TelegramPoster
without any markdown/HTML conversion. Text is used as-is from the database, with minimal
normalization:

-    Reflection newline normalization:
    • Replace any CR/LF line breaks with spaces (collapse newlines into single spaces).
    • Collapse multiple spaces/tabs into a single space.
    • Trim leading/trailing whitespace.

-    Verse formatting:
    • Apply the same normalization as above.
    • After removing newlines, find the last "(" and insert a single newline just BEFORE it.
      If no "(" exists, the verse is unchanged.

-    Optional double-underscore cleanup in subject/verse/reflection/prayer (e.g., "lives__are")
    normalized to a single space.

Requirements:
-    database.py providing init_db, get_devotional, get_random_unread, get_random_read, mark_read
-    telegram_poster.py with TelegramPoster
"""

import argparse
import re
from datetime import date
from typing import Dict, Optional

import database
from telegram_poster import TelegramPoster

# -------------------- Simple normalization helpers --------------------

RE_CRLF = re.compile(r"\r\n?")  # \r\n or \r -> \n
RE_ANY_NEWLINE = re.compile(r"\n+")  # any runs of \n
RE_DOUBLE_SPACE = re.compile(r"[ \t]{2,}")  # 2+ spaces/tabs -> 1 space
RE_MULTI_UNDERSCORES = re.compile(r"_{2,}")  # 2+ underscores -> 1 space


def normalize_simple(text: Optional[str]) -> str:
    """
    Minimal normalization:
    - Convert CR/LF to LF, then collapse all newlines to single spaces.
    - Collapse multiple spaces/tabs to a single space.
    - Strip leading/trailing whitespace.
    """
    if not text:
        return ""
    s = text
    s = RE_CRLF.sub("\n", s)  # unify line endings
    s = RE_ANY_NEWLINE.sub(" ", s)  # collapse any newlines to single spaces
    s = RE_DOUBLE_SPACE.sub(" ", s)  # collapse repeated spaces/tabs
    return s.strip()


def normalize_field(text: Optional[str]) -> str:
    """
    Apply simple normalization plus a gentle cleanup for repeated underscores.
    """
    s = normalize_simple(text)
    s = RE_MULTI_UNDERSCORES.sub(" ", s)
    return s


def format_verse(text: Optional[str]) -> str:
    """
    Normalize verse and then insert a newline just BEFORE the last '(' if present.
    """
    s = normalize_field(text)
    if not s:
        return ""
    last_paren = s.rfind("(")
    if last_paren != -1:
        # Insert a newline before the last '('
        s = s[:last_paren].rstrip() + "\n" + s[last_paren:].lstrip()
    return s


# -------------------- DB record selection --------------------


def pick_devotional(
    message_id: Optional[str], include_read: bool
) -> Optional[Dict[str, str]]:
    database.init_db()  # ensure tables

    if message_id:
        row = database.get_devotional(message_id)
        if not row:
            print(f"No devotional with message_id={message_id}")
            return None
        return dict(row)

    unread = database.get_random_unread(1)
    if unread:
        return dict(unread[0])

    if include_read:
        read_rows = database.get_random_read(1)
        if read_rows:
            return dict(read_rows[0])

    print("No suitable devotional found (no unread left and --include-read not set).")
    return None


# -------------------- CLI and main --------------------


def build_args():
    p = argparse.ArgumentParser(
        description="Post a devotional from the database to Telegram (no markdown/HTML conversion)."
    )
    p.add_argument("--message-id", help="Post a specific devotional by message_id.")
    p.add_argument(
        "--include-read",
        action="store_true",
        help="If no unread remains, allow posting a previously read devotional.",
    )
    p.add_argument(
        "--no-mark",
        action="store_true",
        help="Do not mark the devotional as read after posting.",
    )
    p.add_argument(
        "--silent",
        action="store_true",
        help="Post to Telegram without notification (silent).",
    )
    p.add_argument("--mark-date", help="YYYY-MM-DD to mark as read (default: today).")
    return p.parse_args()


def main():
    args = build_args()

    rec = pick_devotional(message_id=args.message_id, include_read=args.include_read)
    if not rec:
        return

    # Normalize fields for posting
    subject = normalize_field(rec.get("subject"))
    verse = format_verse(rec.get("verse"))  # special rule: newline before last '('
    reflection = normalize_field(rec.get("reflection"))  # replace newlines with spaces
    prayer = normalize_field(rec.get("prayer"))
    reading = (
        normalize_field(rec.get("reading")) if rec.get("reading") is not None else ""
    )

    poster = TelegramPoster()
    if not poster.is_configured():
        print(
            "Telegram not configured. Set DEVOTIONAL_BOT_TOKEN and DEVOTIONAL_GROUP_ID"
        )
        return

    ok = poster.post_devotion(
        message_id=rec.get("message_id", ""),
        subject=subject,
        verse=verse,
        reading=reading,
        reflection=reflection,
        prayer=prayer,
        silent=args.silent,
    )

    if ok and not args.no_mark and not args.message_id:
        database.mark_read([rec["message_id"]], mark_date=date.today().isoformat())
        print(f"Marked as read: {rec['message_id']}")
    elif ok and args.message_id and args.mark_date and not args.no_mark:
        database.mark_read([rec["message_id"]], mark_date=args.mark_date)
        print(f"Marked as read on {args.mark_date}: {rec['message_id']}")
    elif not ok:
        print("Failed to post devotional.")


if __name__ == "__main__":
    main()
