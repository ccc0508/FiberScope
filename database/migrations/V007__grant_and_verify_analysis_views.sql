\encoding UTF8
\set ON_ERROR_STOP 1

-- 植物纤维数据库：分析视图权限与验收
-- 必须在V006之后执行；可以安全重复运行以复核视图和权限。

BEGIN;

SET LOCAL ROLE fiber_owner;
SET LOCAL search_path TO fiber, public;

DO $view_preflight$
DECLARE
    v_actual_views TEXT[];
    v_expected_views CONSTANT TEXT[] := ARRAY[
        'v_beating_analysis',
        'v_blend_analysis',
        'v_data_lineage',
        'v_fiber_paper_analysis',
        'v_sample_overview'
    ];
BEGIN
    SELECT ARRAY_AGG(v.viewname ORDER BY v.viewname)
    INTO v_actual_views
    FROM pg_views AS v
    WHERE v.schemaname = 'fiber';

    IF v_actual_views IS DISTINCT FROM v_expected_views THEN
        RAISE EXCEPTION
            'fiber中的分析视图不符合预期。实际：%，预期：%',
            v_actual_views,
            v_expected_views;
    END IF;
END
$view_preflight$;

GRANT USAGE ON SCHEMA fiber
    TO fiber_importer, fiber_reader;

REVOKE ALL
    ON fiber.v_sample_overview,
       fiber.v_fiber_paper_analysis,
       fiber.v_beating_analysis,
       fiber.v_blend_analysis,
       fiber.v_data_lineage
    FROM PUBLIC, fiber_importer, fiber_reader;

GRANT SELECT
    ON fiber.v_sample_overview,
       fiber.v_fiber_paper_analysis,
       fiber.v_beating_analysis,
       fiber.v_blend_analysis,
       fiber.v_data_lineage
    TO fiber_importer, fiber_reader;

DO $verify_views$
DECLARE
    v_view_name TEXT;
    v_expected_columns INTEGER;
    v_actual_columns INTEGER;
    v_relation REGCLASS;
BEGIN
    FOR v_view_name, v_expected_columns IN
        SELECT *
        FROM (VALUES
            ('v_sample_overview', 12),
            ('v_fiber_paper_analysis', 37),
            ('v_beating_analysis', 38),
            ('v_blend_analysis', 41),
            ('v_data_lineage', 14)
        ) AS expected(view_name, column_count)
    LOOP
        SELECT COUNT(*)::INTEGER
        INTO v_actual_columns
        FROM information_schema.columns AS c
        WHERE c.table_schema = 'fiber'
          AND c.table_name = v_view_name;

        IF v_actual_columns <> v_expected_columns THEN
            RAISE EXCEPTION
                '视图fiber.%应有%个字段，实际为%个',
                v_view_name,
                v_expected_columns,
                v_actual_columns;
        END IF;

        SELECT format('fiber.%I', v_view_name)::REGCLASS
        INTO v_relation;

        IF NOT has_table_privilege('fiber_reader', v_relation, 'SELECT')
           OR NOT has_table_privilege('fiber_importer', v_relation, 'SELECT') THEN
            RAISE EXCEPTION '视图fiber.%缺少只读授权', v_view_name;
        END IF;

        IF has_table_privilege(
               'fiber_reader',
               v_relation,
               'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
           )
           OR has_table_privilege(
               'fiber_importer',
               v_relation,
               'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
           ) THEN
            RAISE EXCEPTION '视图fiber.%存在多余写入权限', v_view_name;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_views AS v
        WHERE v.schemaname = 'fiber'
          AND v.viewowner <> 'fiber_owner'
    ) THEN
        RAISE EXCEPTION '存在所有者不是fiber_owner的分析视图';
    END IF;

    IF (SELECT COUNT(*) FROM fiber.v_sample_overview) <> 61 THEN
        RAISE EXCEPTION 'v_sample_overview应有61行';
    END IF;
    IF (SELECT COUNT(*) FROM fiber.v_fiber_paper_analysis) <> 61 THEN
        RAISE EXCEPTION 'v_fiber_paper_analysis应有61行';
    END IF;
    IF (SELECT COUNT(*) FROM fiber.v_beating_analysis) <> 52 THEN
        RAISE EXCEPTION 'v_beating_analysis应有52行';
    END IF;
    IF (SELECT COUNT(*) FROM fiber.v_blend_analysis) <> 11 THEN
        RAISE EXCEPTION 'v_blend_analysis应有11行';
    END IF;
    IF (SELECT COUNT(*) FROM fiber.v_data_lineage) <> 257 THEN
        RAISE EXCEPTION 'v_data_lineage应有257行';
    END IF;
    IF (SELECT COUNT(DISTINCT source_id) FROM fiber.v_data_lineage) <> 178 THEN
        RAISE EXCEPTION 'v_data_lineage未覆盖全部178条来源记录';
    END IF;
    IF (
        SELECT COUNT(*)
        FROM fiber.v_data_lineage
        WHERE usage_type = 'source_only'
    ) <> 2 THEN
        RAISE EXCEPTION '应有2条仅用于复配端点核对的source_only来源行';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM fiber.v_blend_analysis
        WHERE display_code = 'zk010'
          AND display_order = 1
          AND canonical_code = 'HW_R08000'
          AND sw_proportion_pct = 0
          AND hw_proportion_pct = 100
    ) OR NOT EXISTS (
        SELECT 1
        FROM fiber.v_blend_analysis
        WHERE display_code = 'zk100'
          AND display_order = 11
          AND canonical_code = 'SW_R14000'
          AND sw_proportion_pct = 100
          AND hw_proportion_pct = 0
    ) THEN
        RAISE EXCEPTION '复配视图的两个端点或比例不正确';
    END IF;

    IF NOT has_table_privilege('fiber_reader', 'fiber.sample', 'SELECT')
       OR has_table_privilege(
           'fiber_reader',
           'fiber.sample',
           'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
       ) THEN
        RAISE EXCEPTION 'fiber_reader对基础表的只读权限不符合既有设计';
    END IF;
END
$verify_views$;

COMMIT;

SELECT
    'PASS' AS verification_status,
    5 AS analysis_view_count,
    (SELECT COUNT(*) FROM fiber.v_sample_overview) AS sample_overview_rows,
    (SELECT COUNT(*) FROM fiber.v_fiber_paper_analysis) AS wide_analysis_rows,
    (SELECT COUNT(*) FROM fiber.v_beating_analysis) AS beating_rows,
    (SELECT COUNT(*) FROM fiber.v_blend_analysis) AS blend_rows,
    (SELECT COUNT(*) FROM fiber.v_data_lineage) AS lineage_rows,
    (SELECT COUNT(DISTINCT source_id) FROM fiber.v_data_lineage)
        AS covered_source_rows;
