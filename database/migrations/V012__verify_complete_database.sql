\encoding UTF8
\set ON_ERROR_STOP on
-- Full baseline verification after V011, as administrator. Strictly read-only.
BEGIN READ ONLY;
SET LOCAL search_path TO fiber, public;
DO $verify$
DECLARE item RECORD; actual BIGINT;
BEGIN
  IF current_database() <> 'plant_fiber_db' THEN RAISE EXCEPTION 'Wrong database'; END IF;
  IF (SELECT count(*) FROM pg_tables WHERE schemaname='fiber') <> 11 THEN RAISE EXCEPTION 'Expected 11 tables'; END IF;
  IF (SELECT count(*) FROM pg_views WHERE schemaname='fiber') <> 8 THEN RAISE EXCEPTION 'Expected 8 views'; END IF;
  FOR item IN SELECT * FROM (VALUES
    ('material',3),('experiment',4),('sample',5),('data_source',6),
    ('experiment_sample',5),('sample_component',6),('fiber_measurement',14),('paper_measurement',13),
    ('recycled_dataset',11),('recycled_data_block',16),('recycled_cycle_observation',31)
  ) AS expected(name,n) LOOP
    SELECT count(*) INTO actual FROM information_schema.columns WHERE table_schema='fiber' AND table_name=item.name;
    IF actual <> item.n THEN RAISE EXCEPTION 'Column count mismatch: %', item.name; END IF;
  END LOOP;
  IF (SELECT count(*) FROM information_schema.table_constraints WHERE table_schema='fiber' AND constraint_type='PRIMARY KEY') <> 11
    OR (SELECT count(*) FROM information_schema.table_constraints WHERE table_schema='fiber' AND constraint_type='FOREIGN KEY') <> 13 THEN
    RAISE EXCEPTION 'Primary/foreign key baseline mismatch';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='fiber' AND NOT c.convalidated) THEN
    RAISE EXCEPTION 'An unvalidated constraint exists';
  END IF;
  IF (SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='fiber' AND t.tgname IN ('ctrg_sample_components_on_sample','ctrg_sample_components_on_component')
      AND t.tgenabled='O' AND t.tgdeferrable AND t.tginitdeferred) <> 2 THEN
    RAISE EXCEPTION 'Deferred component constraint triggers missing or disabled';
  END IF;
  FOR item IN SELECT * FROM (VALUES
    ('material',2),('experiment',3),('sample',61),('data_source',178),
    ('experiment_sample',63),('sample_component',70),('fiber_measurement',61),('paper_measurement',61),
    ('recycled_dataset',1),('recycled_data_block',14),('recycled_cycle_observation',131),
    ('v_sample_overview',61),('v_fiber_paper_analysis',61),('v_beating_analysis',52),('v_blend_analysis',11),
    ('v_data_lineage',257),('v_recycled_cycle_detail',131),('v_recycled_cycle_summary',47),('v_recycled_data_quality',4)
  ) AS expected(name, n) LOOP
    EXECUTE format('SELECT count(*) FROM fiber.%I', item.name) INTO actual;
    IF actual <> item.n THEN RAISE EXCEPTION 'Count mismatch: %, %, expected %',item.name,actual,item.n; END IF;
    IF has_table_privilege('fiber_app',format('fiber.%I',item.name),'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') THEN
      RAISE EXCEPTION 'App has write privileges: %',item.name;
    END IF;
    IF has_table_privilege('fiber_app',format('fiber.%I',item.name),'SELECT') <> (left(item.name,2)='v_') THEN
      RAISE EXCEPTION 'App SELECT boundary violated: %',item.name;
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='fiber' AND tableowner <> 'fiber_owner')
     OR EXISTS (SELECT 1 FROM pg_views WHERE schemaname='fiber' AND viewowner <> 'fiber_owner') THEN
    RAISE EXCEPTION 'Incorrect object owner';
  END IF;
  IF EXISTS (SELECT 1 FROM fiber.sample_component GROUP BY sample_id HAVING sum(proportion_pct) <> 100) THEN
    RAISE EXCEPTION 'Component ratio mismatch';
  END IF;
  IF (SELECT array_agg(source_row ORDER BY source_row) FROM fiber.v_recycled_data_quality) <> ARRAY[5,6,13,60] THEN
    RAISE EXCEPTION 'Quality source rows changed';
  END IF;
  IF EXISTS (SELECT 1 FROM fiber.recycled_data_block WHERE condition_label IS NOT NULL OR metadata_status <> 'unknown') THEN
    RAISE EXCEPTION 'Unconfirmed block metadata changed';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM fiber.v_blend_analysis WHERE display_code='zk010' AND canonical_code='HW_R08000')
    OR NOT EXISTS (SELECT 1 FROM fiber.v_blend_analysis WHERE display_code='zk100' AND canonical_code='SW_R14000') THEN
    RAISE EXCEPTION 'Blend endpoint reuse mismatch';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fiber_app' AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) THEN
    RAISE EXCEPTION 'App role has elevated privileges';
  END IF;
END $verify$;
COMMIT;
SELECT 'PASS' AS full_baseline_verification;
