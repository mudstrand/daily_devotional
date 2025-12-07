-- setup_tit_postgres.sql
-- Run as superuser on tit.lan, connected to the "postgres" database.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bible') THEN
        CREATE ROLE bible WITH LOGIN PASSWORD 'bible';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'devotional') THEN
        CREATE ROLE devotional WITH LOGIN PASSWORD 'devotional';
    END IF;
END;
$$;

\set ON_ERROR_STOP off
CREATE DATABASE bible OWNER bible;
CREATE DATABASE devotional OWNER devotional;
\set ON_ERROR_STOP on
