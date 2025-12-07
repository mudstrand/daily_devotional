-- setup_tit_bible_schema.sql
-- Run as superuser against the bible database.

CREATE SCHEMA IF NOT EXISTS bible AUTHORIZATION bible;
GRANT USAGE, CREATE ON SCHEMA bible TO bible;
ALTER ROLE bible SET search_path TO bible, public;