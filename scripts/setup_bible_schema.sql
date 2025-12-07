-- scripts/setup_bible_schema.sql
-- Run connected to the bible database as superuser or owner.

CREATE SCHEMA IF NOT EXISTS bible AUTHORIZATION bible;

-- Privileges for bible role
GRANT USAGE, CREATE ON SCHEMA bible TO bible;
ALTER DEFAULT PRIVILEGES IN SCHEMA bible GRANT ALL ON TABLES TO bible;

-- Optional: set default search_path so unqualified names go to bible first
ALTER ROLE bible SET search_path TO bible, public;
