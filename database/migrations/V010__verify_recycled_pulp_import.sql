\encoding UTF8
-- 再生纸浆循环回用实验：正式入库验收
-- 在V008、V009和正式导入全部成功后执行。本脚本只读，不修改数据。

BEGIN;

SET LOCAL search_path TO fiber, public;

DO $verify$
DECLARE
    v_table_name TEXT;
    v_view_name TEXT;
BEGIN
    IF current_database() <> 'plant_fiber_db' THEN
        RAISE EXCEPTION
            '当前数据库为 %，本验收只能在 plant_fiber_db 中执行',
            current_database();
    END IF;

    FOREACH v_table_name IN ARRAY ARRAY[
        'recycled_dataset',
        'recycled_data_block',
        'recycled_cycle_observation'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'fiber'
              AND table_name = v_table_name
              AND table_type = 'BASE TABLE'
        ) THEN
            RAISE EXCEPTION '缺少表 fiber.%', v_table_name;
        END IF;
    END LOOP;

    FOREACH v_view_name IN ARRAY ARRAY[
        'v_recycled_cycle_detail',
        'v_recycled_cycle_summary',
        'v_recycled_data_quality'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.views
            WHERE table_schema = 'fiber'
              AND table_name = v_view_name
        ) THEN
            RAISE EXCEPTION '缺少视图 fiber.%', v_view_name;
        END IF;
    END LOOP;

    IF (SELECT COUNT(*) FROM fiber.recycled_dataset) <> 1 THEN
        RAISE EXCEPTION 'recycled_dataset应有1行';
    END IF;
    IF (SELECT COUNT(*) FROM fiber.recycled_data_block) <> 14 THEN
        RAISE EXCEPTION 'recycled_data_block应有14行';
    END IF;
    IF (SELECT COUNT(*) FROM fiber.recycled_cycle_observation) <> 131 THEN
        RAISE EXCEPTION 'recycled_cycle_observation应有131行';
    END IF;
    IF (SELECT COUNT(*) FROM fiber.v_recycled_cycle_detail) <> 131 THEN
        RAISE EXCEPTION 'v_recycled_cycle_detail应有131行';
    END IF;
    IF (SELECT COUNT(*) FROM fiber.v_recycled_cycle_summary) <> 47 THEN
        RAISE EXCEPTION 'v_recycled_cycle_summary应有47行';
    END IF;
    IF (SELECT COUNT(*) FROM fiber.v_recycled_data_quality) <> 4 THEN
        RAISE EXCEPTION 'v_recycled_data_quality应有4行';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.recycled_data_block AS b
        LEFT JOIN fiber.recycled_cycle_observation AS o
          ON o.block_id = b.block_id
        GROUP BY
            b.block_id,
            b.cycle_count,
            b.expected_replicates_per_cycle
        HAVING COUNT(*) <> b.cycle_count * b.expected_replicates_per_cycle
    ) THEN
        RAISE EXCEPTION '存在数据块的循环数或重复数不完整';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM fiber.recycled_data_block
        WHERE block_code = 'G11'
          AND block_name = '数据块11'
          AND raw_material_grade = '美废13#'
          AND source_start_row = 118
          AND source_end_row = 121
    ) THEN
        RAISE EXCEPTION '黄色标注的美废13#组映射不正确';
    END IF;

    IF (SELECT COUNT(*) FROM fiber.sample) <> 61
       OR (SELECT COUNT(*) FROM fiber.fiber_measurement) <> 61
       OR (SELECT COUNT(*) FROM fiber.paper_measurement) <> 61 THEN
        RAISE EXCEPTION '原有61个核心样本数据被意外改变';
    END IF;

    IF NOT has_table_privilege(
        'fiber_reader',
        'fiber.v_recycled_cycle_detail',
        'SELECT'
    ) OR has_table_privilege(
        'fiber_reader',
        'fiber.recycled_cycle_observation',
        'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
    ) THEN
        RAISE EXCEPTION 'fiber_reader权限不符合只读设计';
    END IF;

    IF NOT has_table_privilege(
        'fiber_importer',
        'fiber.v_recycled_cycle_detail',
        'SELECT'
    ) OR has_table_privilege(
        'fiber_importer',
        'fiber.v_recycled_cycle_detail',
        'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
    ) THEN
        RAISE EXCEPTION 'fiber_importer对扩展视图不应具有写权限';
    END IF;
END
$verify$;

COMMIT;

SELECT
    'PASS' AS verification_status,
    (SELECT COUNT(*) FROM fiber.recycled_dataset) AS dataset_count,
    (SELECT COUNT(*) FROM fiber.recycled_data_block) AS block_count,
    (SELECT COUNT(*) FROM fiber.v_recycled_cycle_detail) AS observation_count,
    (SELECT COUNT(*) FROM fiber.v_recycled_cycle_summary) AS summary_point_count,
    (SELECT COUNT(*) FROM fiber.v_recycled_data_quality) AS review_row_count,
    (SELECT COUNT(*) FROM fiber.sample) AS original_sample_count;
