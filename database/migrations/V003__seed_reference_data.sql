-- 植物纤维数据库：固定基础数据
-- 必须在V001和V002之后执行。

BEGIN;

SET LOCAL ROLE fiber_owner;
SET LOCAL search_path TO fiber, public;

INSERT INTO fiber.material (
    material_code,
    material_name
)
VALUES
    ('SW', '漂白针叶木浆'),
    ('HW', '漂白阔叶木浆')
ON CONFLICT (material_code)
DO UPDATE SET
    material_name = EXCLUDED.material_name;

INSERT INTO fiber.experiment (
    experiment_code,
    experiment_name,
    experiment_type
)
VALUES
    ('SW_BEATING', '针叶木浆打浆实验', 'beating'),
    ('HW_BEATING', '阔叶木浆打浆实验', 'beating'),
    ('BLEND', '针阔叶木浆复配实验', 'blend')
ON CONFLICT (experiment_code)
DO UPDATE SET
    experiment_name = EXCLUDED.experiment_name,
    experiment_type = EXCLUDED.experiment_type;

DO $seed_check$
BEGIN
    IF (SELECT COUNT(*) FROM fiber.material) <> 2 THEN
        RAISE EXCEPTION
            'material应恰好包含2条基础原料，当前为%条',
            (SELECT COUNT(*) FROM fiber.material);
    END IF;

    IF (SELECT COUNT(*) FROM fiber.experiment) <> 3 THEN
        RAISE EXCEPTION
            'experiment应恰好包含3条基础实验，当前为%条',
            (SELECT COUNT(*) FROM fiber.experiment);
    END IF;
END
$seed_check$;

COMMIT;
