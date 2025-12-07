-- scripts/setup_devotional_db.sql
-- Run connected to the default DB as a superuser (e.g., postgres).

-- 1) Create role/user 'devotional' if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'devotional') THEN
        CREATE ROLE devotional WITH LOGIN PASSWORD 'devotional';
    END IF;
END;
$$;

-- 2) Create database 'devotional' owned by 'devotional' (ignore error if exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'devotional') THEN
        PERFORM pg_catalog.pg_sleep(0);  -- no-op
        EXECUTE 'CREATE DATABASE devotional OWNER devotional';
    END IF;
END;
$$;
