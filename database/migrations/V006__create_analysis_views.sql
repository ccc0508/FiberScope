\encoding UTF8
\set ON_ERROR_STOP 1

-- 植物纤维数据库：可视化分析视图
-- 必须在V005入库验收通过后执行。本迁移只创建视图，不修改实验数据。

BEGIN;

SET LOCAL ROLE fiber_owner;
SET LOCAL search_path TO fiber, public;

DO $preflight$
BEGIN
    IF current_database() <> 'plant_fiber_db' THEN
        RAISE EXCEPTION
            '当前数据库为%，本迁移只能在plant_fiber_db执行',
            current_database();
    END IF;

    IF (SELECT COUNT(*) FROM fiber.sample) <> 61
       OR (SELECT COUNT(*) FROM fiber.data_source) <> 178 THEN
        RAISE EXCEPTION
            '正式数据数量不符合61个样本、178条来源的基线；请先运行V005';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_views
        WHERE schemaname = 'fiber'
          AND viewname IN (
              'v_sample_overview',
              'v_fiber_paper_analysis',
              'v_beating_analysis',
              'v_blend_analysis',
              'v_data_lineage'
          )
    ) THEN
        RAISE EXCEPTION
            'V006分析视图已经存在；一次性迁移不得重复执行';
    END IF;
END
$preflight$;

-- 1. 每个唯一样本一行：样本身份、比例和两种原料的打浆条件。
CREATE VIEW fiber.v_sample_overview AS
SELECT
    s.sample_id,
    s.canonical_code,
    s.sample_type,
    s.display_name,
    s.notes,
    COUNT(sc.material_id)::INTEGER AS component_count,
    COALESCE(
        MAX(sc.proportion_pct) FILTER (WHERE m.material_code = 'SW'),
        0.00
    )::NUMERIC(5, 2) AS sw_proportion_pct,
    COALESCE(
        MAX(sc.proportion_pct) FILTER (WHERE m.material_code = 'HW'),
        0.00
    )::NUMERIC(5, 2) AS hw_proportion_pct,
    MAX(sc.beating_revolutions)
        FILTER (WHERE m.material_code = 'SW') AS sw_beating_revolutions,
    MAX(sc.beating_degree_sr)
        FILTER (WHERE m.material_code = 'SW') AS sw_beating_degree_sr,
    MAX(sc.beating_revolutions)
        FILTER (WHERE m.material_code = 'HW') AS hw_beating_revolutions,
    MAX(sc.beating_degree_sr)
        FILTER (WHERE m.material_code = 'HW') AS hw_beating_degree_sr
FROM fiber.sample AS s
LEFT JOIN fiber.sample_component AS sc
  ON sc.sample_id = s.sample_id
LEFT JOIN fiber.material AS m
  ON m.material_id = sc.material_id
GROUP BY
    s.sample_id,
    s.canonical_code,
    s.sample_type,
    s.display_name,
    s.notes;

COMMENT ON VIEW fiber.v_sample_overview IS
    '每个唯一样本一行，汇总SW/HW比例及各自打浆转数和打浆度';

-- 2. 每个唯一样本一行：将样本条件、12项纤维特性和9项纸张性能横向关联。
CREATE VIEW fiber.v_fiber_paper_analysis AS
SELECT
    so.sample_id,
    so.canonical_code,
    so.sample_type,
    so.display_name,
    so.notes,
    so.component_count,
    so.sw_proportion_pct,
    so.hw_proportion_pct,
    so.sw_beating_revolutions,
    so.sw_beating_degree_sr,
    so.hw_beating_revolutions,
    so.hw_beating_degree_sr,
    fm.fiber_length_arithmetic_mm,
    fm.fiber_length_weighted_mm,
    fm.fiber_width_um,
    fm.fiber_coarseness_mg_m,
    fm.kink_angle_deg,
    fm.kinked_fiber_pct,
    fm.curved_fiber_pct,
    fm.fibrillation_length_pct,
    fm.broken_fiber_pct,
    fm.fines_length_pct,
    fm.fines_weighted_length_pct,
    fm.fines_area_pct,
    pm.basis_weight_g_m2,
    pm.thickness_um,
    pm.burst_index,
    pm.tear_index,
    pm.tensile_index,
    pm.zero_span_tensile,
    pm.surface_roughness,
    pm.air_permeability,
    pm.folding_endurance_raw,
    pm.replicate_count,
    pm.aggregation_method,
    fm.source_id AS fiber_source_id,
    pm.source_id AS paper_source_id
FROM fiber.v_sample_overview AS so
JOIN fiber.fiber_measurement AS fm
  ON fm.sample_id = so.sample_id
JOIN fiber.paper_measurement AS pm
  ON pm.sample_id = so.sample_id;

COMMENT ON VIEW fiber.v_fiber_paper_analysis IS
    '61个唯一样本的分析宽表，保留全部12项纤维特性和9项纸张性能';
COMMENT ON COLUMN fiber.v_fiber_paper_analysis.air_permeability IS
    '透气度数值原样保留；设计暂定单位μm/(Pa·s)，待实验记录确认';
COMMENT ON COLUMN fiber.v_fiber_paper_analysis.folding_endurance_raw IS
    '耐折度原始值；单位待确认';

-- 3. 纯浆打浆过程：每个针叶木或阔叶木实验展示点一行，共52行。
CREATE VIEW fiber.v_beating_analysis AS
SELECT
    e.experiment_id,
    e.experiment_code,
    e.experiment_name,
    es.display_code,
    es.display_order,
    fpa.sample_id,
    fpa.canonical_code,
    fpa.sample_type,
    fpa.display_name,
    CASE
        WHEN fpa.sample_type = 'softwood' THEN 'SW'
        WHEN fpa.sample_type = 'hardwood' THEN 'HW'
    END AS material_code,
    CASE
        WHEN fpa.sample_type = 'softwood' THEN fpa.sw_beating_revolutions
        WHEN fpa.sample_type = 'hardwood' THEN fpa.hw_beating_revolutions
    END AS beating_revolutions,
    CASE
        WHEN fpa.sample_type = 'softwood' THEN fpa.sw_beating_degree_sr
        WHEN fpa.sample_type = 'hardwood' THEN fpa.hw_beating_degree_sr
    END AS beating_degree_sr,
    fpa.fiber_length_arithmetic_mm,
    fpa.fiber_length_weighted_mm,
    fpa.fiber_width_um,
    fpa.fiber_coarseness_mg_m,
    fpa.kink_angle_deg,
    fpa.kinked_fiber_pct,
    fpa.curved_fiber_pct,
    fpa.fibrillation_length_pct,
    fpa.broken_fiber_pct,
    fpa.fines_length_pct,
    fpa.fines_weighted_length_pct,
    fpa.fines_area_pct,
    fpa.basis_weight_g_m2,
    fpa.thickness_um,
    fpa.burst_index,
    fpa.tear_index,
    fpa.tensile_index,
    fpa.zero_span_tensile,
    fpa.surface_roughness,
    fpa.air_permeability,
    fpa.folding_endurance_raw,
    fpa.replicate_count,
    fpa.aggregation_method,
    es.source_id AS experiment_source_id,
    fpa.fiber_source_id,
    fpa.paper_source_id
FROM fiber.experiment_sample AS es
JOIN fiber.experiment AS e
  ON e.experiment_id = es.experiment_id
JOIN fiber.v_fiber_paper_analysis AS fpa
  ON fpa.sample_id = es.sample_id
WHERE e.experiment_code IN ('SW_BEATING', 'HW_BEATING');

COMMENT ON VIEW fiber.v_beating_analysis IS
    '针叶木和阔叶木打浆过程分析视图；按实验与display_order排序使用';

-- 4. 针阔复配过程：包含两个复用端点和9个中间点，共11行。
CREATE VIEW fiber.v_blend_analysis AS
SELECT
    e.experiment_id,
    e.experiment_code,
    e.experiment_name,
    es.display_code,
    es.display_order,
    fpa.sample_id,
    fpa.canonical_code,
    fpa.sample_type,
    fpa.display_name,
    fpa.sw_proportion_pct,
    fpa.hw_proportion_pct,
    fpa.sw_beating_revolutions,
    fpa.sw_beating_degree_sr,
    fpa.hw_beating_revolutions,
    fpa.hw_beating_degree_sr,
    fpa.fiber_length_arithmetic_mm,
    fpa.fiber_length_weighted_mm,
    fpa.fiber_width_um,
    fpa.fiber_coarseness_mg_m,
    fpa.kink_angle_deg,
    fpa.kinked_fiber_pct,
    fpa.curved_fiber_pct,
    fpa.fibrillation_length_pct,
    fpa.broken_fiber_pct,
    fpa.fines_length_pct,
    fpa.fines_weighted_length_pct,
    fpa.fines_area_pct,
    fpa.basis_weight_g_m2,
    fpa.thickness_um,
    fpa.burst_index,
    fpa.tear_index,
    fpa.tensile_index,
    fpa.zero_span_tensile,
    fpa.surface_roughness,
    fpa.air_permeability,
    fpa.folding_endurance_raw,
    fpa.replicate_count,
    fpa.aggregation_method,
    es.source_id AS experiment_source_id,
    fpa.fiber_source_id,
    fpa.paper_source_id
FROM fiber.experiment_sample AS es
JOIN fiber.experiment AS e
  ON e.experiment_id = es.experiment_id
JOIN fiber.v_fiber_paper_analysis AS fpa
  ON fpa.sample_id = es.sample_id
WHERE e.experiment_code = 'BLEND';

COMMENT ON VIEW fiber.v_blend_analysis IS
    '针阔复配分析视图；zk010和zk100复用纯浆样本，其余9行为复配样本';

-- 5. 来源追溯：一个来源行可对应多个用途；未直接引用的端点核对行仍保留。
CREATE VIEW fiber.v_data_lineage AS
WITH source_usage AS (
    SELECT
        es.source_id,
        'experiment_sample'::TEXT AS usage_type,
        es.sample_id,
        e.experiment_code,
        es.display_code,
        NULL::VARCHAR(16) AS material_code
    FROM fiber.experiment_sample AS es
    JOIN fiber.experiment AS e
      ON e.experiment_id = es.experiment_id

    UNION ALL

    SELECT
        sc.source_id,
        'sample_component'::TEXT AS usage_type,
        sc.sample_id,
        NULL::VARCHAR(32) AS experiment_code,
        NULL::VARCHAR(16) AS display_code,
        m.material_code
    FROM fiber.sample_component AS sc
    JOIN fiber.material AS m
      ON m.material_id = sc.material_id

    UNION ALL

    SELECT
        fm.source_id,
        'fiber_measurement'::TEXT AS usage_type,
        fm.sample_id,
        NULL::VARCHAR(32) AS experiment_code,
        NULL::VARCHAR(16) AS display_code,
        NULL::VARCHAR(16) AS material_code
    FROM fiber.fiber_measurement AS fm

    UNION ALL

    SELECT
        pm.source_id,
        'paper_measurement'::TEXT AS usage_type,
        pm.sample_id,
        NULL::VARCHAR(32) AS experiment_code,
        NULL::VARCHAR(16) AS display_code,
        NULL::VARCHAR(16) AS material_code
    FROM fiber.paper_measurement AS pm
)
SELECT
    ds.source_id,
    ds.file_name,
    ds.sheet_name,
    ds.source_row,
    ds.source_version,
    ds.imported_at,
    COALESCE(su.usage_type, 'source_only') AS usage_type,
    su.experiment_code,
    su.display_code,
    su.material_code,
    s.sample_id,
    s.canonical_code,
    s.sample_type,
    s.display_name
FROM fiber.data_source AS ds
LEFT JOIN source_usage AS su
  ON su.source_id = ds.source_id
LEFT JOIN fiber.sample AS s
  ON s.sample_id = su.sample_id;

COMMENT ON VIEW fiber.v_data_lineage IS
    '来源文件行到展示点、组分和测量记录的追溯关系；source_only表示仅用于端点核对';

COMMIT;
