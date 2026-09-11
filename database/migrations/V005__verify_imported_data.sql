\encoding UTF8
\set ON_ERROR_STOP 1

-- 植物纤维数据库：正式数据入库验收
-- 本脚本只读，不修改业务数据；应在8份正式Excel全部导入后执行。

BEGIN TRANSACTION READ ONLY;
SET LOCAL search_path TO fiber, public;

DO $verify_import$
DECLARE
    v_actual INTEGER;
BEGIN
    IF current_database() <> 'plant_fiber_db' THEN
        RAISE EXCEPTION
            '当前数据库为%，验收脚本只能在plant_fiber_db执行',
            current_database();
    END IF;

    IF (SELECT COUNT(*) FROM fiber.material) <> 2
       OR (SELECT COUNT(*) FROM fiber.experiment) <> 3 THEN
        RAISE EXCEPTION '基础原料或实验定义数量不正确';
    END IF;

    IF (SELECT COUNT(*) FROM fiber.sample) <> 61 THEN
        RAISE EXCEPTION 'sample应有61条，实际为%条',
            (SELECT COUNT(*) FROM fiber.sample);
    END IF;
    IF (SELECT COUNT(*) FROM fiber.experiment_sample) <> 63 THEN
        RAISE EXCEPTION 'experiment_sample应有63条，实际为%条',
            (SELECT COUNT(*) FROM fiber.experiment_sample);
    END IF;
    IF (SELECT COUNT(*) FROM fiber.sample_component) <> 70 THEN
        RAISE EXCEPTION 'sample_component应有70条，实际为%条',
            (SELECT COUNT(*) FROM fiber.sample_component);
    END IF;
    IF (SELECT COUNT(*) FROM fiber.fiber_measurement) <> 61 THEN
        RAISE EXCEPTION 'fiber_measurement应有61条，实际为%条',
            (SELECT COUNT(*) FROM fiber.fiber_measurement);
    END IF;
    IF (SELECT COUNT(*) FROM fiber.paper_measurement) <> 61 THEN
        RAISE EXCEPTION 'paper_measurement应有61条，实际为%条',
            (SELECT COUNT(*) FROM fiber.paper_measurement);
    END IF;
    IF (SELECT COUNT(*) FROM fiber.data_source) <> 178 THEN
        RAISE EXCEPTION 'data_source应有178条，实际为%条',
            (SELECT COUNT(*) FROM fiber.data_source);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('softwood', 28),
            ('hardwood', 24),
            ('blend', 9)
        ) AS expected(sample_type, expected_count)
        LEFT JOIN (
            SELECT sample_type, COUNT(*)::INTEGER AS actual_count
            FROM fiber.sample
            GROUP BY sample_type
        ) AS actual USING (sample_type)
        WHERE COALESCE(actual.actual_count, 0) <> expected.expected_count
    ) THEN
        RAISE EXCEPTION '三类唯一样本数量不符合28、24、9的基线';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('SW_BEATING', 28),
            ('HW_BEATING', 24),
            ('BLEND', 11)
        ) AS expected(experiment_code, expected_count)
        JOIN fiber.experiment AS e USING (experiment_code)
        LEFT JOIN (
            SELECT experiment_id, COUNT(*)::INTEGER AS actual_count
            FROM fiber.experiment_sample
            GROUP BY experiment_id
        ) AS actual USING (experiment_id)
        WHERE COALESCE(actual.actual_count, 0) <> expected.expected_count
    ) THEN
        RAISE EXCEPTION '三个实验的展示点数量不符合28、24、11的基线';
    END IF;

    SELECT COUNT(*)::INTEGER
    INTO v_actual
    FROM (VALUES
        ('zk010', 1, 'HW_R08000'),
        ('zk19',  2, 'BLEND_SW010_HW090'),
        ('zk28',  3, 'BLEND_SW020_HW080'),
        ('zk37',  4, 'BLEND_SW030_HW070'),
        ('zk46',  5, 'BLEND_SW040_HW060'),
        ('zk55',  6, 'BLEND_SW050_HW050'),
        ('zk64',  7, 'BLEND_SW060_HW040'),
        ('zk73',  8, 'BLEND_SW070_HW030'),
        ('zk82',  9, 'BLEND_SW080_HW020'),
        ('zk91', 10, 'BLEND_SW090_HW010'),
        ('zk100',11, 'SW_R14000')
    ) AS expected(display_code, display_order, canonical_code)
    JOIN fiber.experiment AS e
      ON e.experiment_code = 'BLEND'
    JOIN fiber.experiment_sample AS es
      ON es.experiment_id = e.experiment_id
     AND es.display_code = expected.display_code
     AND es.display_order = expected.display_order
    JOIN fiber.sample AS s
      ON s.sample_id = es.sample_id
     AND s.canonical_code = expected.canonical_code;

    IF v_actual <> 11 THEN
        RAISE EXCEPTION
            '复配编号、显示顺序或端点复用关系不正确，匹配%/11条',
            v_actual;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.sample AS s
        LEFT JOIN fiber.sample_component AS sc
          ON sc.sample_id = s.sample_id
        LEFT JOIN fiber.material AS m
          ON m.material_id = sc.material_id
        GROUP BY s.sample_id, s.sample_type
        HAVING
            (s.sample_type = 'softwood' AND (
                COUNT(*) <> 1
                OR SUM(sc.proportion_pct) <> 100
                OR COUNT(*) FILTER (WHERE m.material_code = 'SW') <> 1
            ))
            OR
            (s.sample_type = 'hardwood' AND (
                COUNT(*) <> 1
                OR SUM(sc.proportion_pct) <> 100
                OR COUNT(*) FILTER (WHERE m.material_code = 'HW') <> 1
            ))
            OR
            (s.sample_type = 'blend' AND (
                COUNT(*) <> 2
                OR SUM(sc.proportion_pct) <> 100
                OR COUNT(*) FILTER (WHERE m.material_code = 'SW') <> 1
                OR COUNT(*) FILTER (WHERE m.material_code = 'HW') <> 1
            ))
    ) THEN
        RAISE EXCEPTION '存在组分数、原料类型或比例合计不正确的样本';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.sample AS s
        JOIN fiber.sample_component AS sc
          ON sc.sample_id = s.sample_id
        JOIN fiber.material AS m
          ON m.material_id = sc.material_id
        WHERE s.sample_type = 'blend'
          AND (
              (m.material_code = 'SW' AND (
                  sc.beating_revolutions <> 14000
                  OR sc.beating_degree_sr <> 41.0
                  OR sc.proportion_pct <= 0
                  OR sc.proportion_pct >= 100
              ))
              OR
              (m.material_code = 'HW' AND (
                  sc.beating_revolutions <> 8000
                  OR sc.beating_degree_sr <> 40.6
                  OR sc.proportion_pct <= 0
                  OR sc.proportion_pct >= 100
              ))
          )
    ) THEN
        RAISE EXCEPTION '存在不符合固定打浆条件或中间比例要求的复配组分';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.sample AS s
        LEFT JOIN fiber.fiber_measurement AS fm USING (sample_id)
        LEFT JOIN fiber.paper_measurement AS pm USING (sample_id)
        WHERE fm.sample_id IS NULL OR pm.sample_id IS NULL
    ) THEN
        RAISE EXCEPTION '存在缺少纤维或纸张测量记录的唯一样本';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.fiber_measurement
        WHERE fiber_length_arithmetic_mm IS NULL
           OR fiber_length_weighted_mm IS NULL
           OR fiber_width_um IS NULL
           OR fiber_coarseness_mg_m IS NULL
           OR kink_angle_deg IS NULL
           OR kinked_fiber_pct IS NULL
           OR curved_fiber_pct IS NULL
           OR fibrillation_length_pct IS NULL
           OR broken_fiber_pct IS NULL
           OR fines_length_pct IS NULL
           OR fines_weighted_length_pct IS NULL
           OR fines_area_pct IS NULL
    ) THEN
        RAISE EXCEPTION '当前正式来源没有空值，fiber_measurement不应出现NULL';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.paper_measurement
        WHERE basis_weight_g_m2 IS NULL
           OR thickness_um IS NULL
           OR burst_index IS NULL
           OR tear_index IS NULL
           OR tensile_index IS NULL
           OR zero_span_tensile IS NULL
           OR surface_roughness IS NULL
           OR air_permeability IS NULL
           OR folding_endurance_raw IS NULL
           OR replicate_count <> 3
           OR aggregation_method <> '剔除偏差值后取最终均值'
    ) THEN
        RAISE EXCEPTION 'paper_measurement存在NULL或聚合元数据不正确';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('针叶木-打浆转数-打浆度(1).xlsx', '原始版', 28),
            ('针叶木-打浆转数-纤维特性(1).xlsx', '原始版', 28),
            ('针叶木-打浆转数-纸张性能(1).xlsx', '原始版', 28),
            ('data1-阔叶木-打浆转数-打浆度(1).xlsx', '原始版', 24),
            ('data2-阔叶木-打浆转数-纤维特性(1).xlsx', '原始版', 24),
            ('data3-阔叶木-打浆转数-纸张性能(1).xlsx', '原始版', 24),
            ('data4-针阔-复配-纤维特性0110(1).xlsx', '0110', 11),
            ('data5-针阔-复配-纸张特性0110(1).xlsx', '0110', 11)
        ) AS expected(file_name, source_version, expected_count)
        LEFT JOIN (
            SELECT file_name, source_version, COUNT(*)::INTEGER AS actual_count
            FROM fiber.data_source
            GROUP BY file_name, source_version
        ) AS actual
          ON actual.file_name = expected.file_name
         AND actual.source_version = expected.source_version
        WHERE COALESCE(actual.actual_count, 0) <> expected.expected_count
    ) THEN
        RAISE EXCEPTION '8份正式来源的行数或版本不符合基线';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.experiment_sample AS es
        JOIN fiber.experiment AS e USING (experiment_id)
        JOIN fiber.data_source AS ds USING (source_id)
        WHERE (e.experiment_code = 'SW_BEATING'
               AND ds.file_name <> '针叶木-打浆转数-打浆度(1).xlsx')
           OR (e.experiment_code = 'HW_BEATING'
               AND ds.file_name <> 'data1-阔叶木-打浆转数-打浆度(1).xlsx')
           OR (e.experiment_code = 'BLEND'
               AND ds.file_name <> 'data4-针阔-复配-纤维特性0110(1).xlsx')
    ) THEN
        RAISE EXCEPTION 'experiment_sample存在错误的权威来源文件';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.sample_component AS sc
        JOIN fiber.sample AS s USING (sample_id)
        JOIN fiber.data_source AS ds USING (source_id)
        WHERE (s.sample_type = 'softwood'
               AND ds.file_name <> '针叶木-打浆转数-打浆度(1).xlsx')
           OR (s.sample_type = 'hardwood'
               AND ds.file_name <> 'data1-阔叶木-打浆转数-打浆度(1).xlsx')
           OR (s.sample_type = 'blend'
               AND ds.file_name <> 'data4-针阔-复配-纤维特性0110(1).xlsx')
    ) THEN
        RAISE EXCEPTION 'sample_component存在错误的权威来源文件';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.fiber_measurement AS fm
        JOIN fiber.sample AS s USING (sample_id)
        JOIN fiber.data_source AS ds USING (source_id)
        WHERE (s.sample_type = 'softwood'
               AND ds.file_name <> '针叶木-打浆转数-纤维特性(1).xlsx')
           OR (s.sample_type = 'hardwood'
               AND ds.file_name <> 'data2-阔叶木-打浆转数-纤维特性(1).xlsx')
           OR (s.sample_type = 'blend'
               AND ds.file_name <> 'data4-针阔-复配-纤维特性0110(1).xlsx')
    ) THEN
        RAISE EXCEPTION 'fiber_measurement存在错误的来源文件';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiber.paper_measurement AS pm
        JOIN fiber.sample AS s USING (sample_id)
        JOIN fiber.data_source AS ds USING (source_id)
        WHERE (s.sample_type = 'softwood'
               AND ds.file_name <> '针叶木-打浆转数-纸张性能(1).xlsx')
           OR (s.sample_type = 'hardwood'
               AND ds.file_name <> 'data3-阔叶木-打浆转数-纸张性能(1).xlsx')
           OR (s.sample_type = 'blend'
               AND ds.file_name <> 'data5-针阔-复配-纸张特性0110(1).xlsx')
    ) THEN
        RAISE EXCEPTION 'paper_measurement存在错误的来源文件';
    END IF;
END
$verify_import$;

COMMIT;

SELECT
    'PASS' AS verification_status,
    (SELECT COUNT(*) FROM fiber.sample) AS sample_count,
    (SELECT COUNT(*) FROM fiber.experiment_sample) AS experiment_sample_count,
    (SELECT COUNT(*) FROM fiber.sample_component) AS component_count,
    (SELECT COUNT(*) FROM fiber.fiber_measurement) AS fiber_count,
    (SELECT COUNT(*) FROM fiber.paper_measurement) AS paper_count,
    (SELECT COUNT(*) FROM fiber.data_source) AS source_count;
