\encoding UTF8
\set ON_ERROR_STOP on
-- Connect to postgres; CREATE DATABASE must run outside a transaction.
CREATE DATABASE plant_fiber_db TEMPLATE template0 ENCODING 'UTF8';
ALTER DATABASE plant_fiber_db SET timezone TO 'Asia/Shanghai';
REVOKE ALL ON DATABASE plant_fiber_db FROM PUBLIC;
GRANT CONNECT ON DATABASE plant_fiber_db TO fiber_owner, fiber_importer, fiber_reader;
\connect plant_fiber_db
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA fiber AUTHORIZATION fiber_owner;
SET ROLE fiber_owner;
GRANT USAGE ON SCHEMA fiber TO fiber_reader, fiber_importer;
ALTER DEFAULT PRIVILEGES FOR ROLE fiber_owner IN SCHEMA fiber GRANT SELECT ON TABLES TO fiber_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE fiber_owner IN SCHEMA fiber GRANT SELECT, INSERT, UPDATE ON TABLES TO fiber_importer;
ALTER DEFAULT PRIVILEGES FOR ROLE fiber_owner IN SCHEMA fiber GRANT USAGE, SELECT ON SEQUENCES TO fiber_importer;
RESET ROLE;
ALTER ROLE fiber_reader SET search_path TO fiber, public;
ALTER ROLE fiber_importer SET search_path TO fiber, public;
