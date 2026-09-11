-- 植物纤维数据库：空库结构、约束、基础数据和权限验收
-- 本脚本只查询系统目录并抛出验收错误，不写入业务数据。
-- 应在V001、V002、V003全部成功后，以管理员连接plant_fiber_db执行。

BEGIN;

SET LOCAL search_path TO fiber, public;

DO $verify$
DECLARE
    v_actual_tables TEXT[];
    v_expected_tables CONSTANT TEXT[] := ARRAY[
        'data_source',
        'experiment',
        'experiment_sample',
        'fiber_measurement',
        'material',
        'paper_measurement',
        'sample',
        'sample_component'
    ];
    v_table_name TEXT;
    v_expected_columns INTEGER;
    v_actual_columns INTEGER;
    v_wrong_owners INTEGER;
    v_primary_keys INTEGER;
    v_foreign_keys INTEGER;
    v_trigger_count INTEGER;
    v_failed_privileges INTEGER;
BEGIN
    IF current_database() <> 'plant_fiber_db' THEN
        RAISE EXCEPTION
            '当前数据库为 %，验收脚本只能在 plant_fiber_db 中执行',
            current_database();
    END IF;

    IF current_setting('server_encoding') <> 'UTF8' THEN
        RAISE EXCEPTION
            '数据库编码应为UTF8，当前为%',
            current_setting('server_encoding');
    END IF;

    IF current_setting('TimeZone') <> 'Asia/Shanghai' THEN
        RAISE EXCEPTION
            '当前会话时区应为Asia/Shanghai，当前为%；请重新连接后再验收',
            current_setting('TimeZone');
    END IF;

    SELECT ARRAY_AGG(t.table_name ORDER BY t.table_name)
    INTO v_actual_tables
    FROM information_schema.tables AS t
    WHERE t.table_schema = 'fiber'
      AND t.table_type = 'BASE TABLE';

    IF v_actual_tables IS DISTINCT FROM v_expected_tables THEN
        RAISE EXCEPTION
            'fiber中的核心表不符合预期。实际：%，预期：%',
            v_actual_tables,
            v_expected_tables;
    END IF;

    FOR v_table_name, v_expected_columns IN
        SELECT *
        FROM (VALUES
            ('material', 3),
            ('experiment', 4),
            ('sample', 5),
            ('data_source', 6),
            ('experiment_sample', 5),
            ('sample_component', 6),
            ('fiber_measurement', 14),
            ('paper_measurement', 13)
        ) AS expected(table_name, column_count)
    LOOP
        SELECT COUNT(*)::INTEGER
        INTO v_actual_columns
        FROM information_schema.columns AS c
        WHERE c.table_schema = 'fiber'
          AND c.table_name = v_table_name;

        IF v_actual_columns <> v_expected_columns THEN
            RAISE EXCEPTION
                '表fiber.%应有%个字段，实际为%个',
                v_table_name,
                v_expected_columns,
                v_actual_columns;
        END IF;
    END LOOP;

    SELECT COUNT(*)::INTEGER
    INTO v_wrong_owners
    FROM pg_tables AS t
    WHERE t.schemaname = 'fiber'
      AND t.tableowner <> 'fiber_owner';

    IF v_wrong_owners <> 0 THEN
        RAISE EXCEPTION
            '存在%张表的所有者不是fiber_owner',
            v_wrong_owners;
    END IF;

    SELECT COUNT(*)::INTEGER
    INTO v_primary_keys
    FROM information_schema.table_constraints AS tc
    WHERE tc.table_schema = 'fiber'
      AND tc.constraint_type = 'PRIMARY KEY';

    IF v_primary_keys <> 8 THEN
        RAISE EXCEPTION
            '应有8个主键，实际为%个',
            v_primary_keys;
    END IF;

    SELECT COUNT(*)::INTEGER
    INTO v_foreign_keys
    FROM information_schema.table_constraints AS tc
    WHERE tc.table_schema = 'fiber'
      AND tc.constraint_type = 'FOREIGN KEY';

    IF v_foreign_keys <> 10 THEN
        RAISE EXCEPTION
            '应有10个外键，实际为%个',
            v_foreign_keys;
    END IF;

    SELECT COUNT(*)::INTEGER
    INTO v_trigger_count
    FROM pg_trigger AS t
    JOIN pg_class AS c
      ON c.oid = t.tgrelid
    JOIN pg_namespace AS n
      ON n.oid = c.relnamespace
    WHERE n.nspname = 'fiber'
      AND NOT t.tgisinternal
      AND t.tgname IN (
          'ctrg_sample_components_on_sample',
          'ctrg_sample_components_on_component'
      );

    IF v_trigger_count <> 2 THEN
        RAISE EXCEPTION
            '样本组分约束触发器应有2个，实际为%个',
            v_trigger_count;
    END IF;

    IF (SELECT COUNT(*) FROM fiber.material) <> 2 THEN
        RAISE EXCEPTION '基础原料数量不是2';
    END IF;

    IF (SELECT COUNT(*) FROM fiber.experiment) <> 3 THEN
        RAISE EXCEPTION '基础实验数量不是3';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'fiber_importer'
          AND rolcanlogin
          AND NOT rolsuper
          AND NOT rolcreatedb
          AND NOT rolcreaterole
    ) THEN
        RAISE EXCEPTION 'fiber_importer登录或管理权限设置不正确';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'fiber_reader'
          AND rolcanlogin
          AND NOT rolsuper
          AND NOT rolcreatedb
          AND NOT rolcreaterole
    ) THEN
        RAISE EXCEPTION 'fiber_reader登录或管理权限设置不正确';
    END IF;

    IF NOT has_database_privilege(
        'fiber_importer',
        'plant_fiber_db',
        'CONNECT'
    ) OR NOT has_schema_privilege(
        'fiber_importer',
        'fiber',
        'USAGE'
    ) THEN
        RAISE EXCEPTION 'fiber_importer缺少数据库连接或Schema使用权限';
    END IF;

    IF NOT has_database_privilege(
        'fiber_reader',
        'plant_fiber_db',
        'CONNECT'
    ) OR NOT has_schema_privilege(
        'fiber_reader',
        'fiber',
        'USAGE'
    ) THEN
        RAISE EXCEPTION 'fiber_reader缺少数据库连接或Schema使用权限';
    END IF;

    SELECT COUNT(*)::INTEGER
    INTO v_failed_privileges
    FROM pg_class AS c
    JOIN pg_namespace AS n
      ON n.oid = c.relnamespace
    WHERE n.nspname = 'fiber'
      AND c.relkind = 'r'
      AND (
          NOT has_table_privilege(
              'fiber_importer',
              c.oid,
              'SELECT'
          )
          OR has_table_privilege(
              'fiber_importer',
              c.oid,
              'DELETE,TRUNCATE,REFERENCES,TRIGGER'
          )
          OR (
              c.relname IN ('material', 'experiment')
              AND has_table_privilege(
                  'fiber_importer',
                  c.oid,
                  'INSERT,UPDATE'
              )
          )
          OR (
              c.relname NOT IN ('material', 'experiment')
              AND (
                  NOT has_table_privilege(
                      'fiber_importer',
                      c.oid,
                      'INSERT'
                  )
                  OR NOT has_table_privilege(
                      'fiber_importer',
                      c.oid,
                      'UPDATE'
                  )
              )
          )
          OR NOT has_table_privilege(
              'fiber_reader',
              c.oid,
              'SELECT'
          )
          OR has_table_privilege(
              'fiber_reader',
              c.oid,
              'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
          )
      );

    IF v_failed_privileges <> 0 THEN
        RAISE EXCEPTION
            '存在%张表的导入或只读权限不符合设计',
            v_failed_privileges;
    END IF;

    IF NOT has_sequence_privilege(
        'fiber_importer',
        'fiber.sample_sample_id_seq',
        'USAGE'
    ) OR NOT has_sequence_privilege(
        'fiber_importer',
        'fiber.data_source_source_id_seq',
        'USAGE'
    ) THEN
        RAISE EXCEPTION 'fiber_importer缺少样本或来源编号序列权限';
    END IF;

    IF has_sequence_privilege(
        'fiber_importer',
        'fiber.material_material_id_seq',
        'USAGE,SELECT'
    ) OR has_sequence_privilege(
        'fiber_importer',
        'fiber.experiment_experiment_id_seq',
        'USAGE,SELECT'
    ) THEN
        RAISE EXCEPTION 'fiber_importer不应操作基础原料或实验编号序列';
    END IF;

    IF has_sequence_privilege(
        'fiber_reader',
        'fiber.sample_sample_id_seq',
        'USAGE,SELECT'
    ) OR has_sequence_privilege(
        'fiber_reader',
        'fiber.data_source_source_id_seq',
        'USAGE,SELECT'
    ) THEN
        RAISE EXCEPTION 'fiber_reader不应具有任何业务序列权限';
    END IF;
END
$verify$;

COMMIT;

SELECT
    'PASS' AS verification_status,
    current_database() AS database_name,
    current_setting('server_encoding') AS encoding,
    current_setting('TimeZone') AS timezone,
    8 AS core_table_count,
    56 AS field_count,
    2 AS material_count,
    3 AS experiment_count;
