\encoding UTF8
\set ON_ERROR_STOP on
-- Additive, one-time migration. Run as administrator. Set password with \password fiber_app.
BEGIN;
CREATE ROLE fiber_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
GRANT CONNECT ON DATABASE plant_fiber_db TO fiber_app;
GRANT USAGE ON SCHEMA fiber TO fiber_app;
GRANT SELECT ON fiber.v_sample_overview, fiber.v_fiber_paper_analysis,
    fiber.v_beating_analysis, fiber.v_blend_analysis, fiber.v_data_lineage,
    fiber.v_recycled_cycle_detail, fiber.v_recycled_cycle_summary,
    fiber.v_recycled_data_quality TO fiber_app;
ALTER ROLE fiber_app SET search_path TO fiber, public;
ALTER ROLE fiber_app SET default_transaction_read_only TO on;
ALTER ROLE fiber_app SET statement_timeout TO '10s';
COMMIT;
