#!/usr/bin/env python3
# post_devotional_v2.py
import argparse
import os
import random
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from telegram_poster import TelegramPoster

# import your holiday module
try:
    from holiday import Holiday, holiday_info  # noqa: F401
except Exception as e:
    print(f"Failed to import holiday.py: {e}")
    sys.exit(1)

# import bible verse module
try:
    from bible_verse import get_verse_text  # uses include_refs + auto-decorate behavior
except Exception as e:
    print(f"Failed to import bible_verse.py: {e}")
    sys.exit(1)

BIBLE_VERSE_DB = os.getenv("BIBLE_VERSE_DB")
DEVOTIONAL_DB = os.getenv("DEVOTIONAL_DB")
TABLE_DEVOS = "devotionals"
TABLE_USED = "used_devotionals"
DEFAULT_TRANSLATION = "NIV"


# ------------- DB connection -------------
def connect_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=DELETE;")
    conn.execute("PRAGMA synchronous=FULL;")
    return conn


# ------------- Schema -------------
CREATE_USED_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_USED} (
    message_id     TEXT NOT NULL,
    used_key_type  TEXT NOT NULL,   -- 'HOLIDAY' or 'MMDD'
    used_key_value TEXT NOT NULL,   -- holiday enum string OR 'MM-DD'
    used_date      TEXT NOT NULL,   -- 'YYYY-MM-DD' actual posting date
    PRIMARY KEY (message_id, used_key_type, used_key_value),
    FOREIGN KEY (message_id) REFERENCES {TABLE_DEVOS}(message_id)
);
"""

CREATE_USED_IDX_SQL = f"""
CREATE INDEX IF NOT EXISTS idx_used_type_value ON {TABLE_USED}(used_key_type, used_key_value);
"""


def ensure_used_schema(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_USED_SQL)
    conn.execute(CREATE_USED_IDX_SQL)


def ensure_perf_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_devos_mmdd ON {TABLE_DEVOS}(substr(msg_date, 6, 5));"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_devos_holiday ON {TABLE_DEVOS}(holiday);"
    )


# ------------- Helpers -------------
def today_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def to_mmdd(date_iso: str) -> str:
    return date_iso[5:10]


def norm_bool(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y"}


def row_val(r: sqlite3.Row, col: str, default=None):
    try:
        v = r[col]
    except (KeyError, IndexError):
        return default
    return v if v is not None else default


# Scripture reference parsing with comma support:
# "John 3:16", "John 3:16-18", "Ephesians 4:1,2", "Colossians 3:12-14,17"
REF_HEAD_RE = re.compile(
    r"^\s*(?P<book>(?:[1-3]\s+)?[A-Za-z]+(?:\s+[A-Za-z]+)*)\s+(?P<chapter>\d+)\s*:\s*(?P<trail>.+?)\s*$"
)


def _split_verse_trail(trail: str) -> List[str]:
    return [p.strip() for p in trail.split(",") if p.strip()]


def parse_reference_str(ref: str) -> Optional[List[Tuple[str, int, str]]]:
    """
    Return a list of (book, chapter, verse_spec) where verse_spec is 'n' or 'n-m'.
    Handles comma lists like '1,2' or '12-14,17'.
    """
    if not ref:
        return None
    m = REF_HEAD_RE.match(ref)
    if not m:
        return None
    book = m.group("book").strip()
    chapter = int(m.group("chapter"))
    trail = m.group("trail")
    items = _split_verse_trail(trail)
    if not items:
        return None
    result: List[Tuple[str, int, str]] = []
    for item in items:
        vs = item.replace(" ", "")
        if not re.fullmatch(r"\d+(?:-\d+)?", vs):
            return None
        result.append((book, chapter, vs))
    return result


def format_ref_suffix(ref_str: str, translation: str, is_ai: bool) -> str:
    """
    Return '(Malachi 3:6 NIV)', '(Malachi 3:6 NIV AI)',
    or '(Malachi 3:6 NIV • Christmas AI)' if holiday is present.
    """
    pieces: List[str] = (
        [ref_str.strip(), translation.strip()] if ref_str else [translation.strip()]
    )
    # if holiday_val:
    #     pretty = holiday_val.replace("_", " ").title()
    #     pieces.append(f"• {pretty}")
    if is_ai:
        pieces.append("AI")
    inner = " ".join(pieces).strip()
    return f"({inner})" if inner else ""


def fetch_assembled_text_for_ref(
    ref_str: str, translation: str, bible_db: Path
) -> Optional[str]:
    parts = parse_reference_str(ref_str)
    if not parts:
        return None
    texts: List[str] = []
    for book, chapter, verse_spec in parts:
        t = get_verse_text(
            book=book,
            chapter=chapter,
            verse_spec=verse_spec,  # single 'n' or range 'n-m'
            translation=translation,
            db_path=bible_db,
            include_refs=True,
            add_refs_if_missing=True,  # auto-add [n] for NIV
        )
        if t:
            texts.append(t)
    if not texts:
        return None
    return " ".join(texts)


# ------------- Message builder (with bible_verse integration) -------------
def build_message_parts(dev: sqlite3.Row, translation: str, bible_db: Path):
    """
    Returns tuple: (subject, verse_line, reading_line, reflection, prayer, verse_text)
    """
    subject = row_val(dev, "subject", "") or ""
    prayer = row_val(dev, "prayer", "") or ""
    verse_ref_str = (row_val(dev, "verse", "") or "").strip()
    reading_ref_str = (row_val(dev, "reading", "") or "").strip()
    # holiday_val = row_val(dev, "holiday", None)

    ai_subject = norm_bool(row_val(dev, "ai_subject", False))
    ai_prayer = norm_bool(row_val(dev, "ai_prayer", False))
    ai_verse = norm_bool(row_val(dev, "ai_verse", False))
    ai_reading = norm_bool(row_val(dev, "ai_reading", False))

    if ai_subject and subject:
        subject = f"{subject} (AI)"
    if ai_prayer and prayer:
        prayer = f"{prayer} (AI)"

    verse_line = (
        format_ref_suffix(verse_ref_str, translation, ai_verse) if verse_ref_str else ""
    )
    reading_line = (
        format_ref_suffix(reading_ref_str, translation, ai_reading)
        if reading_ref_str
        else ""
    )

    verse_text = (
        fetch_assembled_text_for_ref(verse_ref_str, translation, bible_db)
        if verse_ref_str
        else None
    )

    reflection = (
        row_val(dev, "reflection", "")
        or row_val(dev, "ai_reflection_corrected", "")
        or row_val(dev, "original_content", "")
        or ""
    )

    # (holiday_name, holiday_emoticon) = holiday_vals
    # print(f"holiday_name: {holiday_name}")
    # print(f"holiday_emoticon: {holiday_emoticon}")

    return subject, verse_line, reading_line, reflection, prayer, verse_text


def build_preview_text(parts) -> str:
    subject, verse_line, reading_line, reflection, prayer, verse_text = parts

    lines: List[str] = []
    if subject:
        lines.append(subject)
        lines.append("")

    if reflection:
        lines.append(reflection)
        lines.append("")

    if verse_line:
        lines.append(verse_line)
    if verse_text:
        lines.append(verse_text)
    if verse_line or verse_text:
        lines.append("")

    if reading_line:
        lines.append(reading_line)
        lines.append("")

    if prayer:
        lines.append("Prayer")
        lines.append(prayer)

    return "\n".join(lines).strip()


# ------------- Generic small helper: random pick from candidate IDs -------------
def pick_one_by_ids(
    conn: sqlite3.Connection, id_rows: List[sqlite3.Row]
) -> Optional[sqlite3.Row]:
    if not id_rows:
        return None
    chosen_id = random.choice([r["message_id"] for r in id_rows])
    return conn.execute(
        f"SELECT * FROM {TABLE_DEVOS} WHERE message_id = ?", (chosen_id,)
    ).fetchone()


# ------------- Queries (holiday pools) -------------
def count_catalog_for_holiday(conn: sqlite3.Connection, holiday_value: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM {TABLE_DEVOS} WHERE holiday = ?", (holiday_value,)
    ).fetchone()
    return int(row["cnt"])


def count_remaining_for_holiday(conn: sqlite3.Connection, holiday_value: str) -> int:
    sql = f"""
        WITH used AS (
            SELECT message_id FROM {TABLE_USED}
            WHERE used_key_type = 'HOLIDAY' AND used_key_value = ?
        )
        SELECT COUNT(*) AS cnt
        FROM {TABLE_DEVOS}
        WHERE holiday = ?
          AND message_id NOT IN used
    """
    row = conn.execute(sql, (holiday_value, holiday_value)).fetchone()
    return int(row["cnt"])


def pick_random_unused_for_holiday(
    conn: sqlite3.Connection, holiday_value: str, limit: int = 200
) -> Optional[sqlite3.Row]:
    sql_ids = f"""
        WITH used AS (
            SELECT message_id FROM {TABLE_USED}
            WHERE used_key_type = 'HOLIDAY' AND used_key_value = ?
        )
        SELECT message_id
        FROM {TABLE_DEVOS}
        WHERE holiday = ?
          AND message_id NOT IN used
        LIMIT {limit}
    """
    id_rows = conn.execute(sql_ids, (holiday_value, holiday_value)).fetchall()
    return pick_one_by_ids(conn, id_rows)


def pick_random_any_for_holiday(
    conn: sqlite3.Connection, holiday_value: str, limit: int = 200
) -> Optional[sqlite3.Row]:
    sql_ids = f"""
        SELECT message_id
        FROM {TABLE_DEVOS}
        WHERE holiday = ?
        LIMIT {limit}
    """
    id_rows = conn.execute(sql_ids, (holiday_value,)).fetchall()
    return pick_one_by_ids(conn, id_rows)


def reset_usage_for_holiday(conn: sqlite3.Connection, holiday_value: str) -> None:
    conn.execute(
        f"DELETE FROM {TABLE_USED} WHERE used_key_type = 'HOLIDAY' AND used_key_value = ?",
        (holiday_value,),
    )


# ------------- Queries (MM-DD pools, all) -------------
def count_catalog_for_mmdd(conn: sqlite3.Connection, mmdd: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM {TABLE_DEVOS} WHERE substr(msg_date, 6, 5) = ?",
        (mmdd,),
    ).fetchone()
    return int(row["cnt"])


def count_remaining_for_mmdd(conn: sqlite3.Connection, mmdd: str) -> int:
    sql = f"""
        WITH used AS (
            SELECT message_id FROM {TABLE_USED}
            WHERE used_key_type = 'MMDD' AND used_key_value = ?
        )
        SELECT COUNT(*) AS cnt
        FROM {TABLE_DEVOS}
        WHERE substr(msg_date, 6, 5) = ?
          AND message_id NOT IN used
    """
    row = conn.execute(sql, (mmdd, mmdd)).fetchone()
    return int(row["cnt"])


def pick_random_unused_for_mmdd(
    conn: sqlite3.Connection, mmdd: str, limit: int = 200
) -> Optional[sqlite3.Row]:
    sql_ids = f"""
        WITH used AS (
            SELECT message_id FROM {TABLE_USED}
            WHERE used_key_type = 'MMDD' AND used_key_value = ?
        )
        SELECT message_id
        FROM {TABLE_DEVOS}
        WHERE substr(msg_date, 6, 5) = ?
          AND message_id NOT IN used
        LIMIT {limit}
    """
    id_rows = conn.execute(sql_ids, (mmdd, mmdd)).fetchall()
    return pick_one_by_ids(conn, id_rows)


def pick_random_any_for_mmdd(
    conn: sqlite3.Connection, mmdd: str, limit: int = 200
) -> Optional[sqlite3.Row]:
    sql_ids = f"""
        SELECT message_id
        FROM {TABLE_DEVOS}
        WHERE substr(msg_date, 6, 5) = ?
        LIMIT {limit}
    """
    id_rows = conn.execute(sql_ids, (mmdd,)).fetchall()
    return pick_one_by_ids(conn, id_rows)


def reset_usage_for_mmdd(conn: sqlite3.Connection, mmdd: str) -> None:
    conn.execute(
        f"DELETE FROM {TABLE_USED} WHERE used_key_type = 'MMDD' AND used_key_value = ?",
        (mmdd,),
    )


# ------------- Non-holiday-only helpers -------------
def all_mmdd_remaining_counts_nonholiday(
    conn: sqlite3.Connection,
) -> List[Tuple[str, int]]:
    sql = f"""
        WITH devos AS (
            SELECT substr(msg_date, 6, 5) AS mmdd, message_id
            FROM {TABLE_DEVOS}
            WHERE holiday IS NULL
        ),
        used AS (
            SELECT used_key_value AS mmdd, message_id
            FROM {TABLE_USED}
            WHERE used_key_type = 'MMDD'
        )
        SELECT d.mmdd,
               COUNT(*) FILTER (
                   WHERE d.message_id NOT IN (
                       SELECT u.message_id FROM used u WHERE u.mmdd = d.mmdd
                   )
               ) AS remaining_count
        FROM devos d
        GROUP BY d.mmdd
        ORDER BY remaining_count DESC, d.mmdd
    """
    rows = conn.execute(sql).fetchall()
    return [(r["mmdd"], int(r["remaining_count"])) for r in rows]


def pick_random_unused_for_mmdd_nonholiday(
    conn: sqlite3.Connection, mmdd: str, limit: int = 200
) -> Optional[sqlite3.Row]:
    sql_ids = f"""
        WITH used AS (
            SELECT message_id
            FROM {TABLE_USED}
            WHERE used_key_type = 'MMDD' AND used_key_value = ?
        )
        SELECT message_id
        FROM {TABLE_DEVOS}
        WHERE substr(msg_date, 6, 5) = ?
          AND holiday IS NULL
          AND message_id NOT IN used
        LIMIT {limit}
    """
    id_rows = conn.execute(sql_ids, (mmdd, mmdd)).fetchall()
    return pick_one_by_ids(conn, id_rows)


def pick_random_any_for_mmdd_nonholiday(
    conn: sqlite3.Connection, mmdd: str, limit: int = 200
) -> Optional[sqlite3.Row]:
    sql_ids = f"""
        SELECT message_id
        FROM {TABLE_DEVOS}
        WHERE substr(msg_date, 6, 5) = ?
          AND holiday IS NULL
        LIMIT {limit}
    """
    id_rows = conn.execute(sql_ids, (mmdd,)).fetchall()
    return pick_one_by_ids(conn, id_rows)


def mmdd_in_window(center_mmdd: str, days: int = 14) -> List[str]:
    ref_year = 2021
    center_date = datetime.strptime(f"{ref_year}-{center_mmdd}", "%Y-%m-%d").date()
    mmdd_set = set()
    for delta in range(-days, days + 1):
        d = center_date + timedelta(days=delta)
        mmdd_set.add(d.strftime("%m-%d"))
    return sorted(mmdd_set)


def best_mmdd_in_window_by_remaining_nonholiday(
    conn: sqlite3.Connection, center_mmdd: str, days: int = 14
) -> List[str]:
    window = set(mmdd_in_window(center_mmdd, days))
    counts = all_mmdd_remaining_counts_nonholiday(conn)
    candidates = [(mmdd, cnt) for (mmdd, cnt) in counts if mmdd in window]
    candidates.sort(key=lambda x: (-x[1], x[0]))
    return [mm for mm, _cnt in candidates]


# ------------- Mark used -------------
def mark_used_holiday(
    conn: sqlite3.Connection, message_id: str, used_date_iso: str, holiday_value: str
) -> None:
    conn.execute(
        f"INSERT INTO {TABLE_USED} (message_id, used_key_type, used_key_value, used_date) VALUES (?, 'HOLIDAY', ?, ?)",
        (message_id, holiday_value, used_date_iso),
    )


def mark_used_mmdd(
    conn: sqlite3.Connection, message_id: str, used_date_iso: str, mmdd: str
) -> None:
    conn.execute(
        f"INSERT INTO {TABLE_USED} (message_id, used_key_type, used_key_value, used_date) VALUES (?, 'MMDD', ?, ?)",
        (message_id, mmdd, used_date_iso),
    )


# ------------- Selection orchestration -------------
def select_for_holiday(
    conn: sqlite3.Connection, target_date: str, holiday_value: str
) -> Optional[Tuple[sqlite3.Row, str, str]]:
    total = count_catalog_for_holiday(conn, holiday_value)
    if total <= 0:
        return None
    remaining = count_remaining_for_holiday(conn, holiday_value)
    if remaining > 0:
        row = pick_random_unused_for_holiday(conn, holiday_value)
        if row:
            return (row, "HOLIDAY", holiday_value)
    reset_usage_for_holiday(conn, holiday_value)
    row = pick_random_any_for_holiday(conn, holiday_value)
    if row:
        return (row, "HOLIDAY", holiday_value)
    return None


def select_for_mmdd(
    conn: sqlite3.Connection, target_date: str
) -> Optional[Tuple[sqlite3.Row, str, str]]:
    mmdd = to_mmdd(target_date)
    total = count_catalog_for_mmdd(conn, mmdd)
    if total > 0:
        remaining = count_remaining_for_mmdd(conn, mmdd)
        if remaining > 0:
            row = pick_random_unused_for_mmdd(conn, mmdd)
            if row:
                return (row, "MMDD", mmdd)
        reset_usage_for_mmdd(conn, mmdd)
        row = pick_random_any_for_mmdd(conn, mmdd)
        if row:
            return (row, "MMDD", mmdd)

    window_candidates = best_mmdd_in_window_by_remaining_nonholiday(conn, mmdd, 14)
    for candidate in window_candidates:
        row = pick_random_unused_for_mmdd_nonholiday(conn, candidate)
        if row:
            return (row, "MMDD", candidate)
        reset_usage_for_mmdd(conn, candidate)
        row = pick_random_any_for_mmdd_nonholiday(conn, candidate)
        if row:
            return (row, "MMDD", candidate)

    counts_all = all_mmdd_remaining_counts_nonholiday(conn)
    if counts_all:
        candidates_with_remaining = [mm for mm, cnt in counts_all if cnt > 0]
        search_list = candidates_with_remaining or [mm for mm, _ in counts_all]
        random.shuffle(search_list)
        for candidate in search_list:
            row = pick_random_unused_for_mmdd_nonholiday(conn, candidate)
            if row:
                return (row, "MMDD", candidate)
        top_mmdd = sorted(counts_all, key=lambda x: (-x[1], x[0]))[0][0]
        reset_usage_for_mmdd(conn, top_mmdd)
        row = pick_random_any_for_mmdd_nonholiday(conn, top_mmdd)
        if row:
            return (row, "MMDD", top_mmdd)

    counts_any = _all_mmdd_remaining_counts_any(conn)
    if counts_any:
        chosen_mmdd = counts_any[0][0]
        row = pick_random_unused_for_mmdd(conn, chosen_mmdd)
        if not row:
            reset_usage_for_mmdd(conn, chosen_mmdd)
            row = pick_random_any_for_mmdd(conn, chosen_mmdd)
        if row:
            return (row, "MMDD", chosen_mmdd)

    return None


def _all_mmdd_remaining_counts_any(conn: sqlite3.Connection) -> List[Tuple[str, int]]:
    sql = f"""
        WITH devos AS (
            SELECT substr(msg_date, 6, 5) AS mmdd, message_id
            FROM {TABLE_DEVOS}
        ),
        used AS (
            SELECT used_key_value AS mmdd, message_id
            FROM {TABLE_USED}
            WHERE used_key_type = 'MMDD'
        )
        SELECT d.mmdd,
               COUNT(*) FILTER (
                   WHERE d.message_id NOT IN (
                       SELECT u.message_id FROM used u WHERE u.mmdd = d.mmdd
                   )
               ) AS remaining_count
        FROM devos d
        GROUP BY d.mmdd
        ORDER BY remaining_count DESC, d.mmdd
    """
    rows = conn.execute(sql).fetchall()
    return [(r["mmdd"], int(r["remaining_count"])) for r in rows]


# ------------- Fetch by message_id -------------
def fetch_by_message_id(
    conn: sqlite3.Connection, message_id: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        f"SELECT * FROM {TABLE_DEVOS} WHERE message_id = ?", (message_id,)
    ).fetchone()


def show(v):
    return "None" if v is None else str(v)


# ------------- CLI main -------------
def main():
    # Defaults so they are always defined
    h_enum = None
    holiday_name = None
    holiday_emoticon = None
    ap = argparse.ArgumentParser(
        description="Select and mark a devotional (no posting)."
    )
    ap.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--message-id", help="Force use of a specific message_id")
    ap.add_argument(
        "--translation",
        default=DEFAULT_TRANSLATION,  # ensures NIV by default
        help=f"Bible translation code (default: {DEFAULT_TRANSLATION})",
    )
    ap.add_argument(
        "--devdb", default=str(DEVOTIONAL_DB), help="Path to daily_devotional_v2.db"
    )
    ap.add_argument(
        "--bibledb", default=str(BIBLE_VERSE_DB), help="Path to bible_verse.db"
    )
    ap.add_argument(
        "--test",
        action="store_true",
        help="Test mode: print message to stdout, do not post to Telegram, and do not mark used.",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Preview without marking used"
    )
    args = ap.parse_args()

    # Make --test imply --dry-run
    if args.test:
        args.dry_run = True

    target_date = args.date or today_utc_iso()
    if len(target_date) != 10 or target_date[4] != "-" or target_date[7] != "-":
        print("Invalid --date format. Use YYYY-MM-DD.")
        sys.exit(2)

    dev_db_path = Path(args.devdb)
    if not dev_db_path.exists():
        print(f"Devotional DB not found: {dev_db_path}")
        sys.exit(1)

    bible_db_path = Path(args.bibledb)
    if not bible_db_path.exists():
        print(
            f"[WARN] bible_verse.db not found at {bible_db_path}. Verse text may be missing."
        )

    with connect_sqlite(dev_db_path) as conn:
        with conn:
            ensure_used_schema(conn)
            ensure_perf_indexes(conn)

        with conn:
            if args.message_id:
                row = fetch_by_message_id(conn, args.message_id)
                if not row:
                    print(f"No devotional found with message_id={args.message_id}")
                    sys.exit(1)
                # Determine pool key for marking: prefer holiday if present, else MMDD by msg_date
                holiday_val = row_val(row, "holiday")
                if holiday_val:
                    key_type, key_value = "HOLIDAY", holiday_val
                else:
                    md = row_val(row, "msg_date")
                    if not md or len(md) < 10:
                        print(
                            "Selected row missing or invalid msg_date; cannot determine MMDD pool."
                        )
                        sys.exit(1)
                    key_type, key_value = "MMDD", md[5:10]
            else:
                # date-driven selection (holiday/MMDD ±14-day logic)
                info = holiday_info(target_date)
                if info is None:
                    h_enum = None
                    holiday_name = None
                    holiday_emoticon = None
                else:
                    h_enum, holiday_name, holiday_emoticon = info
                holiday_value = h_enum.value if h_enum is not None else None
                if holiday_value:
                    sel = select_for_holiday(conn, target_date, holiday_value)
                    if not sel:
                        sel = select_for_mmdd(conn, target_date)
                else:
                    sel = select_for_mmdd(conn, target_date)
                if not sel:
                    print("No eligible devotional found under current rules.")
                    sys.exit(1)
                row, key_type, key_value = sel

            parts = build_message_parts(row, args.translation, bible_db_path)
            message_id = row["message_id"]
            subj, verse_line, reading_line, reflection, prayer, verse_text = parts

            # Test mode: print message to stdout and skip posting/marking
            if args.test:
                print("=== TEST MODE PREVIEW ===")
                print(build_preview_text(parts))
                # Optionally show holiday line
                if holiday_name or holiday_emoticon:
                    print("")
                    print(
                        f"Holiday: {holiday_name or ''} {holiday_emoticon or ''}".strip()
                    )
                print("")
                print(f"# {message_id}")
                return

            # Non-test flow:
            if not args.dry_run:
                if key_type == "HOLIDAY":
                    mark_used_holiday(conn, message_id, target_date, key_value)
                else:
                    mark_used_mmdd(conn, message_id, target_date, key_value)
                print(
                    f"Marked used: message_id={message_id} on {target_date} for {key_type}={key_value}"
                )

            poster = TelegramPoster()
            if poster.is_configured():
                poster.post_devotion(
                    message_id=message_id,
                    subject=subj,
                    verse=verse_line,
                    verse_text=verse_text,
                    holiday_name=holiday_name,
                    holiday_emoticon=holiday_emoticon,
                    reading=reading_line,
                    reflection=reflection,
                    prayer=prayer,
                    silent=False,
                )
            else:
                print("[INFO] Telegram not configured; nothing posted.")


if __name__ == "__main__":
    main()
