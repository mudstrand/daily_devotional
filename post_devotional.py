#!/usr/bin/env python3
# post_devotional.py (Postgres via SQLAlchemy)
import argparse
import os
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import (
    create_engine,
    select,
    func,
    text,
    Table,
    Column,
    Text,
    Date,
    MetaData,
    Boolean,
)
from sqlalchemy.engine import Engine, Connection
from sqlalchemy.sql import and_

from telegram_poster import TelegramPoster
from bible_verse import get_verse_text

# import holiday module
try:
    from holiday import Holiday, holiday_info  # noqa: F401
except Exception as e:
    print(f'Failed to import holiday.py: {e}')
    sys.exit(1)

DEVOTIONAL_DATABASE_URL = os.getenv('DEVOTIONAL_DATABASE_URL')
if not DEVOTIONAL_DATABASE_URL:
    print(
        'DEVOTIONAL_DATABASE_URL is not set. Example: postgresql+psycopg://devotional:devotional@127.0.0.1:5432/devotional'
    )
    sys.exit(2)

DEFAULT_TRANSLATION = 'NIV'

# ---------- SQLAlchemy setup ----------
engine: Engine = create_engine(DEVOTIONAL_DATABASE_URL, future=True)

metadata = MetaData()

devotionals = Table(
    'devotionals',
    metadata,
    Column('message_id', Text, primary_key=True),
    Column('msg_date', Text),  # kept as TEXT; substring works
    Column('subject', Text),
    Column('verse', Text),
    Column('reading', Text),
    Column('reflection', Text),
    Column('prayer', Text),
    Column('holiday', Text),
    Column('ai_subject', Boolean),
    Column('ai_prayer', Boolean),
    Column('ai_verse', Boolean),
    Column('ai_reading', Boolean),
    schema='devotional',
)

used_devotionals = Table(
    'used_devotionals',
    metadata,
    Column('message_id', Text, nullable=False),
    Column('used_key_type', Text, nullable=False),  # 'HOLIDAY' or 'MMDD'
    Column('used_key_value', Text, nullable=False),
    Column('used_date', Date, nullable=False),
    schema='devotional',
)


# ---------- Helpers ----------
def today_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def to_mmdd(date_iso: str) -> str:
    return date_iso[5:10]


def norm_bool(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in {'1', 'true', 't', 'yes', 'y'}


def row_val(row, col: str, default=None):
    v = row.get(col) if isinstance(row, dict) else getattr(row, col, None)
    return v if v is not None else default


# Scripture reference parsing with comma support
REF_HEAD_RE = re.compile(
    r'^\s*(?P<book>(?:[1-3]\s+)?[A-Za-z]+(?:\s+[A-Za-z]+)*)\s+(?P<chapter>\d+)\s*:\s*(?P<trail>.+?)\s*$'
)


def _split_verse_trail(trail: str) -> List[str]:
    return [p.strip() for p in trail.split(',') if p.strip()]


def parse_reference_str(ref: str) -> Optional[List[Tuple[str, int, str]]]:
    if not ref:
        return None
    m = REF_HEAD_RE.match(ref)
    if not m:
        return None
    book = m.group('book').strip()
    chapter = int(m.group('chapter'))
    trail = m.group('trail')
    items = _split_verse_trail(trail)
    if not items:
        return None
    result: List[Tuple[str, int, str]] = []
    for item in items:
        vs = item.replace(' ', '')
        if not re.fullmatch(r'\d+(?:-\d+)?', vs):
            return None
        result.append((book, chapter, vs))
    return result


def format_ref_suffix(ref_str: str, translation: str, is_ai: bool) -> str:
    pieces: List[str] = [ref_str.strip(), translation.strip()] if ref_str else [translation.strip()]
    if is_ai:
        pieces.append('AI')
    inner = ' '.join(pieces).strip()
    return f'({inner})' if inner else ''


def fetch_assembled_text_for_ref(ref_str: str, translation: str) -> Optional[str]:
    parts = parse_reference_str(ref_str)
    if not parts:
        return None
    texts: List[str] = []
    for book, chapter, verse_spec in parts:
        t = get_verse_text(
            book=book,
            chapter=chapter,
            verse_spec=verse_spec,  # 'n' or 'n-m'
            translation=translation,
            include_refs=True,
            add_refs_if_missing=True,
        )
        if t:
            texts.append(t)
    if not texts:
        return None
    return ' '.join(texts)


# ---------- Message builder ----------
def build_message_parts(dev_row: dict, translation: str):
    """
    Returns tuple: (subject, verse_line, reading_line, reflection, prayer, verse_text)
    """
    subject = row_val(dev_row, 'subject', '') or ''
    prayer = row_val(dev_row, 'prayer', '') or ''
    verse_ref_str = (row_val(dev_row, 'verse', '') or '').strip()
    reading_ref_str = (row_val(dev_row, 'reading', '') or '').strip()

    ai_subject = norm_bool(row_val(dev_row, 'ai_subject', False))
    ai_prayer = norm_bool(row_val(dev_row, 'ai_prayer', False))
    ai_verse = norm_bool(row_val(dev_row, 'ai_verse', False))
    ai_reading = norm_bool(row_val(dev_row, 'ai_reading', False))

    if ai_subject and subject:
        subject = f'{subject} (AI)'
    if ai_prayer and prayer:
        prayer = f'{prayer} (AI)'

    verse_line = format_ref_suffix(verse_ref_str, translation, ai_verse) if verse_ref_str else ''
    reading_line = format_ref_suffix(reading_ref_str, translation, ai_reading) if reading_ref_str else ''

    verse_text = fetch_assembled_text_for_ref(verse_ref_str, translation) if verse_ref_str else None

    reflection = (
        row_val(dev_row, 'reflection', '')
        or row_val(dev_row, 'ai_reflection_corrected', '')
        or row_val(dev_row, 'original_content', '')
        or ''
    )

    return subject, verse_line, reading_line, reflection, prayer, verse_text


def build_preview_text(parts) -> str:
    subject, verse_line, reading_line, reflection, prayer, verse_text = parts
    lines: List[str] = []
    if subject:
        lines.append(subject)
        lines.append('')
    if reflection:
        lines.append(reflection)
        lines.append('')
    if verse_line:
        lines.append(verse_line)
    if verse_text:
        lines.append(verse_text)
    if verse_line or verse_text:
        lines.append('')
    if reading_line:
        lines.append(reading_line)
        lines.append('')
    if prayer:
        lines.append('Prayer')
        lines.append(prayer)
    return '\n'.join(lines).strip()


# ---------- DB query helpers (SQLAlchemy Core) ----------
def pick_one_by_ids(conn: Connection, id_rows: List[dict]) -> Optional[dict]:
    if not id_rows:
        return None
    chosen_id = random.choice([r['message_id'] for r in id_rows])
    row = conn.execute(select(devotionals).where(devotionals.c.message_id == chosen_id)).mappings().first()
    return dict(row) if row else None


def count_catalog_for_holiday(conn: Connection, holiday_value: str) -> int:
    stmt = select(func.count().label('cnt')).where(devotionals.c.holiday == holiday_value)
    return int(conn.execute(stmt).scalar_one())


def count_remaining_for_holiday(conn: Connection, holiday_value: str) -> int:
    used_subq = (
        select(used_devotionals.c.message_id)
        .where(
            and_(
                used_devotionals.c.used_key_type == 'HOLIDAY',
                used_devotionals.c.used_key_value == holiday_value,
            )
        )
        .subquery()
    )
    stmt = select(func.count().label('cnt')).where(
        and_(
            devotionals.c.holiday == holiday_value,
            ~devotionals.c.message_id.in_(select(used_subq.c.message_id)),
        )
    )
    return int(conn.execute(stmt).scalar_one())


def pick_random_unused_for_holiday(conn: Connection, holiday_value: str, limit: int = 200) -> Optional[dict]:
    used_subq = (
        select(used_devotionals.c.message_id)
        .where(
            and_(
                used_devotionals.c.used_key_type == 'HOLIDAY',
                used_devotionals.c.used_key_value == holiday_value,
            )
        )
        .subquery()
    )
    ids_stmt = (
        select(devotionals.c.message_id)
        .where(
            and_(
                devotionals.c.holiday == holiday_value,
                ~devotionals.c.message_id.in_(select(used_subq.c.message_id)),
            )
        )
        .limit(limit)
    )
    id_rows = [dict(r) for r in conn.execute(ids_stmt).mappings().all()]
    return pick_one_by_ids(conn, id_rows)


def pick_random_any_for_holiday(conn: Connection, holiday_value: str, limit: int = 200) -> Optional[dict]:
    ids_stmt = select(devotionals.c.message_id).where(devotionals.c.holiday == holiday_value).limit(limit)
    id_rows = [dict(r) for r in conn.execute(ids_stmt).mappings().all()]
    return pick_one_by_ids(conn, id_rows)


def reset_usage_for_holiday(conn: Connection, holiday_value: str) -> None:
    conn.execute(
        used_devotionals.delete().where(
            and_(
                used_devotionals.c.used_key_type == 'HOLIDAY',
                used_devotionals.c.used_key_value == holiday_value,
            )
        )
    )


def count_catalog_for_mmdd(conn: Connection, mmdd: str) -> int:
    expr = func.substring(devotionals.c.msg_date, 6, 5)
    stmt = select(func.count().label('cnt')).where(expr == mmdd)
    return int(conn.execute(stmt).scalar_one())


def count_remaining_for_mmdd(conn: Connection, mmdd: str) -> int:
    expr = func.substring(devotionals.c.msg_date, 6, 5)
    used_subq = (
        select(used_devotionals.c.message_id)
        .where(
            and_(
                used_devotionals.c.used_key_type == 'MMDD',
                used_devotionals.c.used_key_value == mmdd,
            )
        )
        .subquery()
    )
    stmt = select(func.count().label('cnt')).where(
        and_(expr == mmdd, ~devotionals.c.message_id.in_(select(used_subq.c.message_id)))
    )
    return int(conn.execute(stmt).scalar_one())


def pick_random_unused_for_mmdd(conn: Connection, mmdd: str, limit: int = 200) -> Optional[dict]:
    expr = func.substring(devotionals.c.msg_date, 6, 5)
    used_subq = (
        select(used_devotionals.c.message_id)
        .where(
            and_(
                used_devotionals.c.used_key_type == 'MMDD',
                used_devotionals.c.used_key_value == mmdd,
            )
        )
        .subquery()
    )
    ids_stmt = (
        select(devotionals.c.message_id)
        .where(
            and_(
                expr == mmdd,
                ~devotionals.c.message_id.in_(select(used_subq.c.message_id)),
            )
        )
        .limit(limit)
    )
    id_rows = [dict(r) for r in conn.execute(ids_stmt).mappings().all()]
    return pick_one_by_ids(conn, id_rows)


def pick_random_any_for_mmdd(conn: Connection, mmdd: str, limit: int = 200) -> Optional[dict]:
    expr = func.substring(devotionals.c.msg_date, 6, 5)
    ids_stmt = select(devotionals.c.message_id).where(expr == mmdd).limit(limit)
    id_rows = [dict(r) for r in conn.execute(ids_stmt).mappings().all()]
    return pick_one_by_ids(conn, id_rows)


def reset_usage_for_mmdd(conn: Connection, mmdd: str) -> None:
    conn.execute(
        used_devotionals.delete().where(
            and_(
                used_devotionals.c.used_key_type == 'MMDD',
                used_devotionals.c.used_key_value == mmdd,
            )
        )
    )


def all_mmdd_remaining_counts_nonholiday(conn: Connection) -> List[Tuple[str, int]]:
    expr = func.substring(devotionals.c.msg_date, 6, 5)
    # Build counts with a manual SQL for FILTER syntax
    sql = text("""
        WITH devos AS (
            SELECT substring(msg_date from 6 for 5) AS mmdd, message_id
            FROM devotional.devotionals
            WHERE holiday IS NULL
        ),
        used AS (
            SELECT used_key_value AS mmdd, message_id
            FROM devotional.used_devotionals
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
    """)
    rows = conn.execute(sql).mappings().all()
    return [(r['mmdd'], int(r['remaining_count'])) for r in rows]


def pick_random_unused_for_mmdd_nonholiday(conn: Connection, mmdd: str, limit: int = 200) -> Optional[dict]:
    sql = text("""
        WITH used AS (
            SELECT message_id
            FROM devotional.used_devotionals
            WHERE used_key_type = 'MMDD' AND used_key_value = :mmdd
        )
        SELECT message_id
        FROM devotional.devotionals
        WHERE substring(msg_date from 6 for 5) = :mmdd
          AND holiday IS NULL
          AND message_id NOT IN (SELECT message_id FROM used)
        LIMIT :limit
    """)
    id_rows = [dict(r) for r in conn.execute(sql, {'mmdd': mmdd, 'limit': limit}).mappings().all()]
    return pick_one_by_ids(conn, id_rows)


def pick_random_any_for_mmdd_nonholiday(conn: Connection, mmdd: str, limit: int = 200) -> Optional[dict]:
    sql = text("""
        SELECT message_id
        FROM devotional.devotionals
        WHERE substring(msg_date from 6 for 5) = :mmdd
          AND holiday IS NULL
        LIMIT :limit
    """)
    id_rows = [dict(r) for r in conn.execute(sql, {'mmdd': mmdd, 'limit': limit}).mappings().all()]
    return pick_one_by_ids(conn, id_rows)


def _all_mmdd_remaining_counts_any(conn: Connection) -> List[Tuple[str, int]]:
    sql = text("""
        WITH devos AS (
            SELECT substring(msg_date from 6 for 5) AS mmdd, message_id
            FROM devotional.devotionals
        ),
        used AS (
            SELECT used_key_value AS mmdd, message_id
            FROM devotional.used_devotionals
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
    """)
    rows = conn.execute(sql).mappings().all()
    return [(r['mmdd'], int(r['remaining_count'])) for r in rows]


def fetch_by_message_id(conn: Connection, message_id: str) -> Optional[dict]:
    row = conn.execute(select(devotionals).where(devotionals.c.message_id == message_id)).mappings().first()
    return dict(row) if row else None


def mark_used_holiday(conn: Connection, message_id: str, used_date_iso: str, holiday_value: str) -> None:
    conn.execute(
        used_devotionals.insert().values(
            message_id=message_id,
            used_key_type='HOLIDAY',
            used_key_value=holiday_value,
            used_date=used_date_iso,
        )
    )


def mark_used_mmdd(conn: Connection, message_id: str, used_date_iso: str, mmdd: str) -> None:
    conn.execute(
        used_devotionals.insert().values(
            message_id=message_id,
            used_key_type='MMDD',
            used_key_value=mmdd,
            used_date=used_date_iso,
        )
    )


# ---------- Selection orchestration ----------
def select_for_holiday(conn: Connection, target_date: str, holiday_value: str) -> Optional[Tuple[dict, str, str]]:
    total = count_catalog_for_holiday(conn, holiday_value)
    if total <= 0:
        return None
    remaining = count_remaining_for_holiday(conn, holiday_value)
    if remaining > 0:
        row = pick_random_unused_for_holiday(conn, holiday_value)
        if row:
            return (row, 'HOLIDAY', holiday_value)
    reset_usage_for_holiday(conn, holiday_value)
    row = pick_random_any_for_holiday(conn, holiday_value)
    if row:
        return (row, 'HOLIDAY', holiday_value)
    return None


def select_for_mmdd(conn: Connection, target_date: str) -> Optional[Tuple[dict, str, str]]:
    mmdd = to_mmdd(target_date)
    total = count_catalog_for_mmdd(conn, mmdd)
    if total > 0:
        remaining = count_remaining_for_mmdd(conn, mmdd)
        if remaining > 0:
            row = pick_random_unused_for_mmdd(conn, mmdd)
            if row:
                return (row, 'MMDD', mmdd)
        reset_usage_for_mmdd(conn, mmdd)
        row = pick_random_any_for_mmdd(conn, mmdd)
        if row:
            return (row, 'MMDD', mmdd)

    window_candidates = best_mmdd_in_window_by_remaining_nonholiday(conn, mmdd, 14)
    for candidate in window_candidates:
        row = pick_random_unused_for_mmdd_nonholiday(conn, candidate)
        if row:
            return (row, 'MMDD', candidate)
        reset_usage_for_mmdd(conn, candidate)
        row = pick_random_any_for_mmdd_nonholiday(conn, candidate)
        if row:
            return (row, 'MMDD', candidate)

    counts_all = all_mmdd_remaining_counts_nonholiday(conn)
    if counts_all:
        candidates_with_remaining = [mm for mm, cnt in counts_all if cnt > 0]
        search_list = candidates_with_remaining or [mm for mm, _ in counts_all]
        random.shuffle(search_list)
        for candidate in search_list:
            row = pick_random_unused_for_mmdd_nonholiday(conn, candidate)
            if row:
                return (row, 'MMDD', candidate)
        top_mmdd = sorted(counts_all, key=lambda x: (-x[1], x[0]))[0][0]
        reset_usage_for_mmdd(conn, top_mmdd)
        row = pick_random_any_for_mmdd_nonholiday(conn, top_mmdd)
        if row:
            return (row, 'MMDD', top_mmdd)

    counts_any = _all_mmdd_remaining_counts_any(conn)
    if counts_any:
        chosen_mmdd = counts_any[0][0]
        row = pick_random_unused_for_mmdd(conn, chosen_mmdd)
        if not row:
            reset_usage_for_mmdd(conn, chosen_mmdd)
            row = pick_random_any_for_mmdd(conn, chosen_mmdd)
        if row:
            return (row, 'MMDD', chosen_mmdd)

    return None


def mmdd_in_window(center_mmdd: str, days: int = 14) -> List[str]:
    ref_year = 2021
    center_date = datetime.strptime(f'{ref_year}-{center_mmdd}', '%Y-%m-%d').date()
    mmdd_set = set()
    for delta in range(-days, days + 1):
        d = center_date + timedelta(days=delta)
        mmdd_set.add(d.strftime('%m-%d'))
    return sorted(mmdd_set)


# ---------- CLI main ----------
def main():
    h_enum = None
    holiday_name = None
    holiday_emoticon = None

    ap = argparse.ArgumentParser(description='Select and mark a devotional (no posting).')
    ap.add_argument('--date', help='YYYY-MM-DD (default: today UTC)')
    ap.add_argument('--message-id', help='Force use of a specific message_id')
    ap.add_argument(
        '--translation',
        default=DEFAULT_TRANSLATION,
        help=f'Bible translation code (default: {DEFAULT_TRANSLATION})',
    )
    ap.add_argument(
        '--test',
        action='store_true',
        help='Test mode: print message to stdout, do not post to Telegram, and do not mark used.',
    )
    ap.add_argument('--dry-run', action='store_true', help='Preview without marking used')
    args = ap.parse_args()

    if args.test:
        args.dry_run = True

    target_date = args.date or today_utc_iso()
    if len(target_date) != 10 or target_date[4] != '-' or target_date[7] != '-':
        print('Invalid --date format. Use YYYY-MM-DD.')
        sys.exit(2)

    with engine.begin() as conn:
        if args.message_id:
            row = fetch_by_message_id(conn, args.message_id)
            if not row:
                print(f'No devotional found with message_id={args.message_id}')
                sys.exit(1)
            holiday_val = row_val(row, 'holiday')
            if holiday_val:
                key_type, key_value = 'HOLIDAY', holiday_val
            else:
                md = row_val(row, 'msg_date')
                if not md or len(md) < 10:
                    print('Selected row missing or invalid msg_date; cannot determine MMDD pool.')
                    sys.exit(1)
                key_type, key_value = 'MMDD', md[5:10]
        else:
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
                print('No eligible devotional found under current rules.')
                sys.exit(1)
            row, key_type, key_value = sel

        parts = build_message_parts(row, args.translation)
        message_id = row['message_id']
        subj, verse_line, reading_line, reflection, prayer, verse_text = parts

        if args.test:
            print('=== TEST MODE PREVIEW ===')
            print(build_preview_text(parts))
            if holiday_name or holiday_emoticon:
                print('')
                print(f'Holiday: {holiday_name or ""} {holiday_emoticon or ""}'.strip())
            print('')
            print(f'# {message_id}')
            return

        if not args.dry_run:
            if key_type == 'HOLIDAY':
                mark_used_holiday(conn, message_id, target_date, key_value)
            else:
                mark_used_mmdd(conn, message_id, target_date, key_value)
            print(f'Marked used: message_id={message_id} on {target_date} for {key_type}={key_value}')

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
            print('[INFO] Telegram not configured; nothing posted.')


if __name__ == '__main__':
    main()
