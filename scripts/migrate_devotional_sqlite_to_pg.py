import os

from sqlalchemy import create_engine, text

sqlite_path = os.getenv('DEVOTIONAL_DB')  # e.g., /Users/mark/shared/daily_devotional.db
pg_url = os.getenv(
    'DEVOTIONAL_DATABASE_URL'
)  # e.g., postgresql+psycopg://devotional:devotional@127.0.0.1:5432/devotional

if not sqlite_path or not pg_url:
    raise SystemExit('Set DEVOTIONAL_DB and DEVOTIONAL_DATABASE_URL')

src = create_engine(f'sqlite:///{sqlite_path}', future=True)
dst = create_engine(pg_url, future=True)

with src.connect() as sconn, dst.begin() as dconn:
    # Copy devotionals
    rows = (
        sconn.execute(
            text("""
        SELECT message_id, msg_date, subject, verse, reading, reflection, prayer,
               holiday, ai_subject, ai_prayer, ai_verse, ai_reading
        FROM devotionals
    """)
        )
        .mappings()
        .all()
    )

    for r in rows:
        dconn.execute(
            text("""
            INSERT INTO devotional.devotionals
                (message_id, msg_date, subject, verse, reading, reflection, prayer,
                 holiday, ai_subject, ai_prayer, ai_verse, ai_reading)
            VALUES
                (:message_id, :msg_date, :subject, :verse, :reading, :reflection, :prayer,
                 :holiday, :ai_subject, :ai_prayer, :ai_verse, :ai_reading)
            ON CONFLICT (message_id) DO NOTHING
        """),
            dict(r),
        )

    # Copy used_devotionals if present in SQLite
    try:
        used_rows = (
            sconn.execute(
                text("""
            SELECT message_id, used_key_type, used_key_value, used_date
            FROM used_devotionals
        """)
            )
            .mappings()
            .all()
        )
        for r in used_rows:
            dconn.execute(
                text("""
                INSERT INTO devotional.used_devotionals
                    (message_id, used_key_type, used_key_value, used_date)
                VALUES
                    (:message_id, :used_key_type, :used_key_value, :used_date)
                ON CONFLICT (message_id, used_key_type, used_key_value) DO NOTHING
            """),
                dict(r),
            )
    except Exception:
        pass

print(f'Copied {len(rows)} devotionals.')
