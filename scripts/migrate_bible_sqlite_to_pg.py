import os
from sqlalchemy import create_engine, text

sqlite_path = os.getenv("BIBLE_VERSE_DB")  # e.g., /Users/mark/shared/bible_verse.db
pg_url = os.getenv(
    "BIBLE_VERSE_DATABASE_URL"
)  # e.g., postgresql+psycopg://bible:bible@127.0.0.1:5432/bible

if not sqlite_path or not pg_url:
    raise SystemExit("Set BIBLE_VERSE_DB and BIBLE_VERSE_DATABASE_URL")

src = create_engine(f"sqlite:///{sqlite_path}", future=True)
dst = create_engine(pg_url, future=True)

with src.connect() as sconn, dst.begin() as dconn:
    rows = (
        sconn.execute(
            text("SELECT book, chapter, verse, translation, text FROM verses")
        )
        .mappings()
        .all()
    )
    for r in rows:
        dconn.execute(
            text("""
                INSERT INTO bible.verses (book, chapter, verse, translation, text)
                VALUES (:book, :chapter, :verse, :translation, :text)
                ON CONFLICT (book, chapter, verse, translation) DO NOTHING
            """),
            dict(r),
        )

print(f"Copied {len(rows)} rows.")
