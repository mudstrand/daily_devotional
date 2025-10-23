# database.py
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date
from typing import Any, Dict, Iterable, Optional

DB_PATH = os.getenv("DEVOTIONAL_DB")


@contextmanager
def get_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn(DB_PATH) as conn:
        # Main parsed table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS devotionals (
            message_id      TEXT PRIMARY KEY,
            date_utc        TEXT,
            subject         TEXT,
            verse           TEXT,
            reflection      TEXT,
            prayer          TEXT,
            identified      INTEGER NOT NULL CHECK (identified IN (0,1)),
            sender          TEXT,
            raw_html        TEXT,
            normalized_text TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT
        )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_devotionals_date ON devotionals(date_utc)"
        )

        # Failures table (ids we couldn't parse; no duplication)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS parse_failures (
            message_id  TEXT PRIMARY KEY,
            reason      TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS read_history (
                message_id  TEXT PRIMARY KEY,
                read_date   TEXT NOT NULL  -- YYYY-MM-DD
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_read_history_date ON read_history(read_date)"
        )


def upsert_devotional(
    rec: Dict[str, Any],
    sender: Optional[str] = None,
    save_raw_html: bool = False,
    save_normalized_text: bool = False,
    db_path: str = DB_PATH,
) -> None:
    """
    Insert/update a successfully parsed devotional. DO NOT call this for unidentified/failed messages.
    """
    with get_conn(db_path) as conn:
        conn.execute(
            """
        INSERT INTO devotionals (
            message_id, date_utc, subject, verse, reflection, prayer, identified,
            sender, raw_html, normalized_text, updated_at
        )
        VALUES (:message_id, :date_utc, :subject, :verse, :reflection, :prayer, :identified,
                :sender, :raw_html, :normalized_text, :updated_at)
        ON CONFLICT(message_id) DO UPDATE SET
            date_utc        = excluded.date_utc,
            subject         = excluded.subject,
            verse           = excluded.verse,
            reflection      = excluded.reflection,
            prayer          = excluded.prayer,
            identified      = excluded.identified,
            sender          = COALESCE(excluded.sender, sender),
            raw_html        = COALESCE(excluded.raw_html, raw_html),
            normalized_text = COALESCE(excluded.normalized_text, normalized_text),
            updated_at      = excluded.updated_at
        """,
            {
                "message_id": rec.get("message_id"),
                "date_utc": rec.get("date"),
                "subject": rec.get("subject"),
                "verse": rec.get("verse"),
                "reflection": rec.get("reflection"),
                "prayer": rec.get("prayer"),
                "identified": 1,  # only call this for identified=True
                "sender": sender,
                "raw_html": rec.get("raw_html") if save_raw_html else None,
                "normalized_text": rec.get("debug_text")
                if save_normalized_text
                else None,
                "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
            },
        )


def record_failure(
    message_id: str,
    reason: Optional[str] = None,
    db_path: str = DB_PATH,
) -> None:
    """
    Remember a parsing failure without touching the main table. Idempotent by PK.
    """
    with get_conn(db_path) as conn:
        conn.execute(
            """
        INSERT OR IGNORE INTO parse_failures (message_id, reason)
        VALUES (?, ?)
        """,
            (message_id, reason or ""),
        )


def get_devotional(message_id: str, db_path: str = DB_PATH) -> Optional[sqlite3.Row]:
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM devotionals WHERE message_id = ?", (message_id,)
        ).fetchone()


def get_recent(limit: int = 20, db_path: str = DB_PATH) -> Iterable[sqlite3.Row]:
    with get_conn(db_path) as conn:
        yield from conn.execute(
            "SELECT * FROM devotionals ORDER BY date_utc DESC, created_at DESC LIMIT ?",
            (limit,),
        )


def get_failures(limit: int = 100, db_path: str = DB_PATH) -> Iterable[sqlite3.Row]:
    with get_conn(db_path) as conn:
        yield from conn.execute(
            "SELECT * FROM parse_failures ORDER BY created_at DESC LIMIT ?", (limit,)
        )


def get_random_unread(limit: int, db_path: str = DB_PATH):
    """
    Return up to 'limit' random unread devotionals (never in read_history).
    """
    with get_conn(db_path) as conn:
        return list(
            conn.execute(
                """
        SELECT d.message_id, d.subject, d.verse, d.reading, d.reflection, d.prayer
        FROM devotionals d
        LEFT JOIN read_history r ON r.message_id = d.message_id
        WHERE r.message_id IS NULL
        ORDER BY RANDOM()
        LIMIT ?
        """,
                (limit,),
            )
        )


def get_random_read(limit: int, db_path: str = DB_PATH):
    """
    Return up to 'limit' random previously read devotionals (fallback when not enough unread).
    """
    with get_conn(db_path) as conn:
        return list(
            conn.execute(
                """
        SELECT d.message_id, d.subject, d.verse, d.reflection, d.prayer
        FROM devotionals d
        INNER JOIN read_history r ON r.message_id = d.message_id
        ORDER BY RANDOM()
        LIMIT ?
        """,
                (limit,),
            )
        )


def mark_read(
    message_ids: list[str], mark_date: Optional[str] = None, db_path: str = DB_PATH
) -> None:
    """
    Mark message_ids as read on mark_date (YYYY-MM-DD). Defaults to today's local date.
    Idempotent (PRIMARY KEY on read_history).
    """
    if not message_ids:
        return
    if not mark_date:
        mark_date = date.today().isoformat()
    with get_conn(db_path) as conn:
        conn.executemany(
            """
        INSERT OR REPLACE INTO read_history (message_id, read_date)
        VALUES (?, ?)
        """,
            [(mid, mark_date) for mid in message_ids],
        )


def unmark_read(message_id: str, db_path: str = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM read_history WHERE message_id = ?", (message_id,))


def search_devotionals(query: str, limit: int = 50, db_path: str = DB_PATH):
    like = f"%{query}%"
    with get_conn(db_path) as conn:
        return list(
            conn.execute(
                """
            SELECT message_id, subject, verse, reflection, prayer
            FROM devotionals
            WHERE subject LIKE ? OR verse LIKE ? OR reflection LIKE ? OR prayer LIKE ?
            ORDER BY date_utc DESC
            LIMIT ?
            """,
                (like, like, like, like, limit),
            )
        )
