# db_bible.py
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

BIBLE_VERSE_DATABASE_URL = os.getenv('BIBLE_VERSE_DATABASE_URL')
if not BIBLE_VERSE_DATABASE_URL:
    raise RuntimeError('BIBLE_VERSE_DATABASE_URL must be set for Bible DB')

engine: Engine = create_engine(BIBLE_VERSE_DATABASE_URL, future=True)
