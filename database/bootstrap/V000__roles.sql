\encoding UTF8
\set ON_ERROR_STOP on
-- Run once on a fresh PostgreSQL instance as its administrator.
-- Passwords are intentionally absent: use psql \password interactively.
CREATE ROLE fiber_owner NOLOGIN;
CREATE ROLE fiber_importer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE fiber_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
