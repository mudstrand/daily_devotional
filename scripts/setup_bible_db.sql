-- scripts/setup_bible_db.sql
-- Run as superuser (postgres). Creates role, DB, schema, and grants.

-- Create role/user (ignore errors if exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bible') THEN
        CREATE ROLE bible WITH LOGIN PASSWORD 'bible';
    END IF;
END;
$$;

-- Create database (ignore errors if exists). If it fails, run this outside DO:
-- CREATE DATABASE bible OWNER bible;
-- For simplicity, try directly:
CREATE DATABASE bible OWNER bible;

-- Connect to the bible database from your shell after running this:
-- psql "postgresql://postgres@HOST:PORT/bible" -f scripts/setup_bible_schema.sql
