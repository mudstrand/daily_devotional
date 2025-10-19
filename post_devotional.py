#!/usr/bin/env python3
"""
post_devotional.py

Reads one devotional from the SQLite database, converts its text to Telegram-safe HTML,
and posts it via telegram_poster.TelegramPoster.

Highlights:
-  Balanced-first emphasis conversion:
    • If bold (**) markers are globally unbalanced, all ** are dropped (no conversion).
    • If single-underscore (_) italics are unbalanced, drop single _ markers (keep __ literal).
    • If single-asterisk (*) italics are unbalanced, drop single * markers (keep ** bold intact).
  Otherwise, matched pairs are converted to <b>...</b> and <i>...</i> safely.

-  Paragraph handling:
    • Keeps blank lines (paragraph breaks).
    • Joins single newlines within paragraphs (soft wraps) into spaces.
    • No <br> tags (Telegram HTML expects literal newlines).

-  Spacing:
    • Adds spacing around <b>/<i> tags so tags don’t jam against words/punctuation.

-  Amen cleanup:
    • Removes stray markers immediately around the word “Amen”.

Requirements:
-  database.py providing init_db, get_devotional, get_random_unread, get_random_read, mark_read
-  telegram_poster.py with TelegramPoster using parse_mode="HTML"
"""

import argparse
import html
import re
from datetime import date
from typing import Optional, Dict

import database
from telegram_poster import TelegramPoster

# -------------------- Regex utilities and placeholders --------------------

RE_CRLF = re.compile(r"\r\n?")
RE_MANY_BLANKS = re.compile(r"\n{3,}")  # 3+ blank lines -> 2
RE_MARKER_ONLY = re.compile(r"(?m)^\s*([*_]{1,3})\s*$")
RE_DOUBLE_SPACE = re.compile(r"[ \t]{2,}")

# Placeholders to survive HTML escaping
B_OPEN, B_CLOSE = "«B»", "«/B»"
I_OPEN, I_CLOSE = "«I»", "«/I»"

# -------------------- Normalization --------------------


def normalize_structure_balanced(s: str) -> str:
    """
    Normalize line endings and paragraph structure:
    - Keep paragraph breaks (blank lines).
    - Within each paragraph, join single newlines to spaces.
    - Remove lines that are only markers like "**" or "_".
    """
    if not s:
        return ""
    s = RE_CRLF.sub("\n", s)
    s = RE_MARKER_ONLY.sub("", s)

    blocks = [b.strip() for b in s.split("\n\n") if b.strip()]
    joined = []
    for b in blocks:
        # Join single newlines within a paragraph
        b = re.sub(r"(?<!\n)\n(?!\n)", " ", b)
        joined.append(b)

    s = "\n\n".join(joined)
    s = RE_MANY_BLANKS.sub("\n\n", s)
    return s.strip()


# -------------------- Balance checks --------------------


def is_bold_balanced(s: str) -> bool:
    # Count non-overlapping occurrences of ** (ignore *** by letting it count as ** + *)
    tokens = re.findall(r"\*\*(?!\*)", s)
    return len(tokens) % 2 == 0


def is_asterisk_ital_balanced(s: str) -> bool:
    # Count single * that are not part of ** (and not escaped)
    tokens = re.findall(r"(?<!\*)\*(?!\*)", s)
    return len(tokens) % 2 == 0


def is_underscore_ital_balanced(s: str) -> bool:
    # Count single _ that are not part of __ (and not escaped)
    tokens = re.findall(r"(?<!_)_(?!_)", s)
    return len(tokens) % 2 == 0


# -------------------- Conversion to Telegram-safe HTML --------------------


def add_spacing_around_tags(html_text: str) -> str:
    """
    Insert spaces around <b>…</b> and <i>…</i> when adjacent to non-space chars,
    except at line starts/ends.
    """
    # Space before opening tag if previous char is not whitespace/newline
    html_text = re.sub(r"(?<![\s\n])(<b>|<i>)", r" \1", html_text)
    # Space after closing tag if followed by non-space and not newline
    html_text = re.sub(r"(</b>|</i>)(?=[^\s\n])", r"\1 ", html_text)
    # Trim line-leading spaces introduced by the above
    html_text = re.sub(r"\n +", "\n", html_text)
    # Collapse multiple spaces
    html_text = RE_DOUBLE_SPACE.sub(" ", html_text)
    # Avoid space before punctuation
    html_text = re.sub(r"\s+([,;:.!?])", r"\1", html_text)
    return html_text


def clean_leftover_markers_around_tags(s: str) -> str:
    """
    Remove raw markers glued to tag boundaries or left dangling at line ends.
    """
    # Remove markers just before a closing tag or just after an opening tag
    s = re.sub(r"(?:\*\*|__|\*|_)+(</[bi]>)", r"\1", s)
    s = re.sub(r"(<[bi]>)\s*(?:\*\*|__|\*|_)+", r"\1", s)
    # Remove trailing markers at end of lines
    s = re.sub(r"[ \t]*(?:\*\*|__|\*|_)+\s*(?=\n|$)", "", s)
    return s


def normalize_amen(html_text: str) -> str:
    """
    Remove stray markdown markers (**, __, *, _) immediately adjacent to 'Amen'
    (case-insensitive), preserving the period if present.
    """
    if not html_text:
        return html_text
    s = RE_DOUBLE_SPACE.sub(" ", html_text)
    # Remove markers before Amen
    s = re.sub(r"(?i)(?:\s*(?:\*\*|__|\*|_)\s*)+(Amen)(\b)", r" \1\2", s)
    # Remove markers after Amen (with optional punctuation)
    s = re.sub(r"(?i)(Amen)([.!?]?)\s*(?:\*\*|__|\*|_)+(\s*$)", r"\1\2\3", s)
    # Case where punctuation is after markers: Amen** .
    s = re.sub(r"(?i)(Amen)\s*(?:\*\*|__|\*|_)+\s*([.!?])(\s*$)", r"\1\2\3", s)
    # Tidy spaces around punctuation and newlines
    s = re.sub(r"\s+([.!?])", r"\1", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    return s


def convert_balanced_md_to_html(s: str) -> str:
    """
    Balanced-first conversion:
    - If ** markers are unbalanced globally, drop all ** (no bold).
    - If single _ markers are unbalanced, drop single _ (keep __ as literal).
    - If single * markers are unbalanced, drop single * (keep ** for bold).
    - Otherwise, convert matched pairs to <b>/<i> using placeholders, then escape and restore.
    Keeps paragraphs (blank lines) and literal newlines for Telegram HTML.
    """
    if not s:
        return ""

    s = normalize_structure_balanced(s)

    # 1) Bold decision
    if is_bold_balanced(s):
        s = re.sub(
            r"\*\*(.+?)\*\*",
            lambda m: f"{B_OPEN}{m.group(1)}{B_CLOSE}",
            s,
            flags=re.DOTALL,
        )
    else:
        # Reduce *** -> ** + * then strip all ** to plain text
        s = s.replace("***", "*")
        s = s.replace("**", "")

    # 2) Underscore italics decision (single _ only)
    if is_underscore_ital_balanced(s):
        s = re.sub(
            r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)",
            lambda m: f"{I_OPEN}{m.group(1)}{I_CLOSE}",
            s,
            flags=re.DOTALL,
        )
    else:
        s = re.sub(r"(?<!_)_(?!_)", "", s)

    # 3) Asterisk italics decision (single * only)
    if is_asterisk_ital_balanced(s):
        s = re.sub(
            r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
            lambda m: f"{I_OPEN}{m.group(1)}{I_CLOSE}",
            s,
            flags=re.DOTALL,
        )
    else:
        s = re.sub(r"(?<!\*)\*(?!\*)", "", s)

    # 4) Escape remaining text
    s = html.escape(s, quote=True)

    # 5) Restore placeholders to HTML tags
    s = s.replace(B_OPEN, "<b>").replace(B_CLOSE, "</b>")
    s = s.replace(I_OPEN, "<i>").replace(I_CLOSE, "</i>")

    # 6) Tidy around tags and remove leftover markers
    s = add_spacing_around_tags(s)
    s = clean_leftover_markers_around_tags(s)

    # 7) Final whitespace cleanup
    s = RE_DOUBLE_SPACE.sub(" ", s)
    s = RE_MANY_BLANKS.sub("\n\n", s)
    return s.strip()


def to_html_field(raw: Optional[str]) -> str:
    return convert_balanced_md_to_html(raw or "")


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


# -------------------- Format fields for Telegram HTML --------------------


def format_for_html(rec: Dict[str, Optional[str]]) -> Dict[str, str]:
    subject_html = to_html_field(rec.get("subject"))
    verse_html = to_html_field(rec.get("verse"))
    refl_html = to_html_field(rec.get("reflection"))
    prayer_html = to_html_field(rec.get("prayer"))

    # Post-conversion cleanups
    verse_html = collapse_literal_underscores(verse_html)
    refl_html = collapse_literal_underscores(refl_html)
    prayer_html = collapse_literal_underscores(prayer_html)

    # Targeted Amen cleanup
    prayer_html = normalize_amen(prayer_html)

    # Also collapse accidental double spaces in verse (e.g., "lives  are")
    verse_html = RE_DOUBLE_SPACE.sub(" ", verse_html)

    return {
        "message_id": html.escape(rec.get("message_id") or "", quote=True),
        "subject": subject_html,
        "verse": verse_html,
        "reflection": refl_html,
        "prayer": prayer_html,
    }


def collapse_literal_underscores(s: str) -> str:
    """
    Replace literal runs of underscores (two or more) with a single space.
    Operates on the final HTML-safe text (so it won't affect tags).
    """
    if not s:
        return s
    return re.sub(r"_{2,}", " ", s)


# -------------------- CLI and main --------------------


def build_args():
    p = argparse.ArgumentParser(
        description="Post a devotional (HTML) from the database to Telegram."
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

    # fmt = format_for_html(rec)
    # print(f"rec: {rec}")

    poster = TelegramPoster()
    if not poster.is_configured():
        print(
            "Telegram not configured. Set DEVOTIONAL_BOT_TOKEN and DEVOTIONAL_GROUP_ID"
        )
        return

    ok = poster.post_devotion(
        message_id=rec["message_id"],
        subject=rec["subject"],
        verse=rec["verse"],
        reading=rec["reading"],
        reflection=rec["reflection"],
        prayer=rec["prayer"],
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
