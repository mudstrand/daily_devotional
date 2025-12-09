# models.py
from sqlalchemy import (
    MetaData,
    Table,
    Column,
    Text,
    Integer,
    Boolean,
    Date,
    PrimaryKeyConstraint,
)

metadata = MetaData()

# Bible schema
verses = Table(
    'verses',
    metadata,
    Column('book', Text, nullable=False),
    Column('chapter', Integer, nullable=False),
    Column('verse', Integer, nullable=False),
    Column('translation', Text, nullable=False),
    Column('text', Text, nullable=False),
    PrimaryKeyConstraint('book', 'chapter', 'verse', 'translation', name='pk_verses'),
    schema='bible',
)

# Devotional schema
devotionals = Table(
    'devotionals',
    metadata,
    Column('message_id', Text, primary_key=True),
    Column('msg_date', Text),  # you can migrate to Date later
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
    Column('used_key_type', Text, nullable=False),
    Column('used_key_value', Text, nullable=False),
    Column('used_date', Date, nullable=False),
    PrimaryKeyConstraint('message_id', 'used_key_type', 'used_key_value', name='pk_used_devotionals'),
    schema='devotional',
)
