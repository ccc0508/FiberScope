\encoding UTF8
-- 再生纸浆循环回用实验：分析视图与只读权限
-- 必须在V008之后执行；本迁移只创建视图，不写入实验数据。

BEGIN;

SET LOCAL ROLE fiber_owner;
SET LOCAL search_path TO fiber, public;

DO $preflight$
BEGIN
    IF current_database() <> 'plant_fiber_db' THEN
        RAISE EXCEPTION
            '当前数据库为 %，本迁移只能在 plant_fiber_db 中执行',
            current_database();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'fiber'
          AND table_name = 'recycled_cycle_observation'
    ) THEN
        RAISE EXCEPTION '请先执行V008创建再生纸浆实验表';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_views
        WHERE schemaname = 'fiber'
          AND viewname IN (
              'v_recycled_cycle_detail',
              'v_recycled_cycle_summary',
              'v_recycled_data_quality'
          )
    ) THEN
        RAISE EXCEPTION 'V009目标视图已存在，请勿重复执行迁移';
    END IF;
END
$preflight$;

-- 1. 逐行明细视图：每一条Excel数值行对应一行。
CREATE VIEW fiber.v_recycled_cycle_detail AS
SELECT
    d.dataset_code,
    d.study_name,
    d.file_name,
    d.sheet_name,
    d.source_version,
    b.block_code,
    b.block_name,
    b.block_order,
    b.section_no,
    b.contributor_name,
    b.raw_material_grade,
    b.material_assignment_basis,
    b.condition_label,
    b.metadata_status,
    o.cycle_no,
    o.replicate_no,
    o.source_row,
    o.length_0_2_0_3_pct,
    o.length_0_3_0_45_pct,
    o.length_0_45_0_67_pct,
    o.length_0_67_1_pct,
    o.length_1_1_5_pct,
    o.length_1_5_2_24_pct,
    o.length_2_24_3_35_pct,
    o.length_3_35_5_01_pct,
    o.length_5_01_7_5_pct,
    o.length_gt_7_5_pct,
    o.length_0_2_0_3_pct
        + o.length_0_3_0_45_pct
        + o.length_0_45_0_67_pct
        + o.length_0_67_1_pct
        + o.length_1_1_5_pct
        + o.length_1_5_2_24_pct
        + o.length_2_24_3_35_pct
        + o.length_3_35_5_01_pct
        + o.length_5_01_7_5_pct
        + o.length_gt_7_5_pct AS length_distribution_sum_pct,
    CASE
        WHEN ABS(
            o.length_0_2_0_3_pct
            + o.length_0_3_0_45_pct
            + o.length_0_45_0_67_pct
            + o.length_0_67_1_pct
            + o.length_1_1_5_pct
            + o.length_1_5_2_24_pct
            + o.length_2_24_3_35_pct
            + o.length_3_35_5_01_pct
            + o.length_5_01_7_5_pct
            + o.length_gt_7_5_pct
            - 100
        ) > 1 THEN 'REVIEW'
        ELSE 'PASS'
    END AS length_distribution_qc,
    o.fiber_length_arithmetic_mm,
    o.fiber_length_weighted_mm,
    o.fiber_width_um,
    o.fiber_coarseness_mg_m,
    o.kink_angle_deg,
    o.kinked_fiber_pct,
    o.curved_fiber_pct,
    o.fibrillation_length_pct,
    o.broken_fiber_pct,
    o.fines_length_pct,
    o.fines_weighted_length_pct,
    o.fines_area_pct,
    o.tensile_strength_kn_m,
    o.burst_strength_kpa,
    o.tear_strength_mn
FROM fiber.recycled_cycle_observation AS o
JOIN fiber.recycled_data_block AS b
  ON b.block_id = o.block_id
 AND b.dataset_id = o.dataset_id
JOIN fiber.recycled_dataset AS d
  ON d.dataset_id = o.dataset_id;

COMMENT ON VIEW fiber.v_recycled_cycle_detail IS
    '再生纸浆循环实验逐行明细；131条源数据入库后应有131行';

-- 2. 数据块×循环均值视图：可直接绘制循环变化曲线。
CREATE VIEW fiber.v_recycled_cycle_summary AS
SELECT
    dataset_code,
    study_name,
    block_code,
    block_name,
    block_order,
    section_no,
    contributor_name,
    raw_material_grade,
    condition_label,
    metadata_status,
    cycle_no,
    COUNT(*)::SMALLINT AS replicate_count,
    AVG(length_0_2_0_3_pct) AS length_0_2_0_3_pct,
    AVG(length_0_3_0_45_pct) AS length_0_3_0_45_pct,
    AVG(length_0_45_0_67_pct) AS length_0_45_0_67_pct,
    AVG(length_0_67_1_pct) AS length_0_67_1_pct,
    AVG(length_1_1_5_pct) AS length_1_1_5_pct,
    AVG(length_1_5_2_24_pct) AS length_1_5_2_24_pct,
    AVG(length_2_24_3_35_pct) AS length_2_24_3_35_pct,
    AVG(length_3_35_5_01_pct) AS length_3_35_5_01_pct,
    AVG(length_5_01_7_5_pct) AS length_5_01_7_5_pct,
    AVG(length_gt_7_5_pct) AS length_gt_7_5_pct,
    AVG(fiber_length_arithmetic_mm) AS fiber_length_arithmetic_mm,
    AVG(fiber_length_weighted_mm) AS fiber_length_weighted_mm,
    AVG(fiber_width_um) AS fiber_width_um,
    AVG(fiber_coarseness_mg_m) AS fiber_coarseness_mg_m,
    AVG(kink_angle_deg) AS kink_angle_deg,
    AVG(kinked_fiber_pct) AS kinked_fiber_pct,
    AVG(curved_fiber_pct) AS curved_fiber_pct,
    AVG(fibrillation_length_pct) AS fibrillation_length_pct,
    AVG(broken_fiber_pct) AS broken_fiber_pct,
    AVG(fines_length_pct) AS fines_length_pct,
    AVG(fines_weighted_length_pct) AS fines_weighted_length_pct,
    AVG(fines_area_pct) AS fines_area_pct,
    AVG(tensile_strength_kn_m) AS tensile_strength_kn_m,
    AVG(burst_strength_kpa) AS burst_strength_kpa,
    AVG(tear_strength_mn) AS tear_strength_mn
FROM fiber.v_recycled_cycle_detail
GROUP BY
    dataset_code,
    study_name,
    block_code,
    block_name,
    block_order,
    section_no,
    contributor_name,
    raw_material_grade,
    condition_label,
    metadata_status,
    cycle_no;

COMMENT ON VIEW fiber.v_recycled_cycle_summary IS
    '再生纸浆循环实验按数据块和循环次数聚合；入库后应有47个数据块×循环分析点';

-- 3. 质量复核视图：只列长度分布合计偏离100%超过1个百分点的原始行。
CREATE VIEW fiber.v_recycled_data_quality AS
SELECT
    dataset_code,
    block_code,
    cycle_no,
    replicate_no,
    source_row,
    length_distribution_sum_pct,
    length_distribution_sum_pct - 100 AS deviation_from_100_pct,
    length_distribution_qc
FROM fiber.v_recycled_cycle_detail
WHERE length_distribution_qc = 'REVIEW';

COMMENT ON VIEW fiber.v_recycled_data_quality IS
    '长度分布占比合计质量复核清单；原值保留，不自动归一化';

REVOKE ALL
    ON fiber.v_recycled_cycle_detail,
       fiber.v_recycled_cycle_summary,
       fiber.v_recycled_data_quality
    FROM PUBLIC, fiber_importer, fiber_reader;

GRANT SELECT
    ON fiber.v_recycled_cycle_detail,
       fiber.v_recycled_cycle_summary,
       fiber.v_recycled_data_quality
    TO fiber_importer, fiber_reader;

COMMIT;
