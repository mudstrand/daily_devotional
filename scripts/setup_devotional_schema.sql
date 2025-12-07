-- scripts/setup_devotional_schema.sql
-- Run connected to the 'devotional' database as superuser or owner.

-- 1) Create a dedicated schema and give ownership to 'devotional'
CREATE SCHEMA IF NOT EXISTS devotional AUTHORIZATION devotional;

-- 2) Privileges for 'devotional' role on schema and future tables
GRANT USAGE, CREATE ON SCHEMA devotional TO devotional;
ALTER DEFAULT PRIVILEGES IN SCHEMA devotional
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO devotional;

-- Optional: make unqualified names resolve to devotional first
ALTER ROLE devotional SET search_path TO devotional, public;

-- 3) Tables (adjust columns if needed)
CREATE TABLE IF NOT EXISTS devotional.devotionals (
    message_id   TEXT PRIMARY KEY,
    msg_date     TEXT,           -- keep as TEXT for now (YYYY-MM-DD)
    subject      TEXT,
    verse        TEXT,
    reading      TEXT,
    reflection   TEXT,
    prayer       TEXT,
    holiday      TEXT,
    ai_subject   BOOLEAN,
    ai_prayer    BOOLEAN,
    ai_verse     BOOLEAN,
    ai_reading   BOOLEAN
);

CREATE TABLE IF NOT EXISTS devotional.used_devotionals (
    message_id     TEXT NOT NULL,
    used_key_type  TEXT NOT NULL,   -- 'HOLIDAY' or 'MMDD'
    used_key_value TEXT NOT NULL,   -- e.g., 'Christmas' or '12-25'
    used_date      DATE NOT NULL,   -- posting date
    PRIMARY KEY (message_id, used_key_type, used_key_value),
    FOREIGN KEY (message_id) REFERENCES devotional.devotionals(message_id)
);

-- 4) Helpful indexes (optional)
CREATE INDEX IF NOT EXISTS idx_devos_mmdd
    ON devotional.devotionals (substring(msg_date from 6 for 5));
CREATE INDEX IF NOT EXISTS idx_used_type_value
    ON devotional.used_devotionals (used_key_type, used_key_value);
