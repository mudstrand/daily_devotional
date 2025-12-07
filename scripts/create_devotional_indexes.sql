-- scripts/create_devotional_indexes.sql
-- Creates helpful indexes for the devotional database (schema: devotional)

-- 1) Index for fast lookups by MM-DD when msg_date is stored as TEXT 'YYYY-MM-DD'
CREATE INDEX IF NOT EXISTS idx_devos_mmdd
    ON devotional.devotionals (substring(msg_date from 6 for 5));

-- 2) Index for used_devotionals lookups by key type and value
CREATE INDEX IF NOT EXISTS idx_used_type_value
    ON devotional.used_devotionals (used_key_type, used_key_value);
