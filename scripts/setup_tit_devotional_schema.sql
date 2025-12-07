-- setup_tit_devotional_schema.sql
-- Run as superuser against the devotional database.

CREATE SCHEMA IF NOT EXISTS devotional AUTHORIZATION devotional;
GRANT USAGE, CREATE ON SCHEMA devotional TO devotional;
ALTER ROLE devotional SET search_path TO devotional, public;