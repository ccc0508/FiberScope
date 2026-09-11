-- 植物纤维数据库：样本组分跨行约束
-- 作用：在事务提交前检查纯浆/复配的组分数、原料、比例和复配固定打浆条件。
-- 必须在V001之后执行。

BEGIN;

SET LOCAL ROLE fiber_owner;
SET LOCAL search_path TO fiber, public;

CREATE FUNCTION fiber.trg_assert_sample_components()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, fiber
AS $function$
DECLARE
    v_sample_ids BIGINT[];
    v_sample_id BIGINT;
    v_sample_type VARCHAR(16);
    v_component_count INTEGER;
    v_total NUMERIC(7, 2);
    v_sw_count INTEGER;
    v_hw_count INTEGER;
    v_all_intermediate BOOLEAN;
    v_sw_fixed_condition BOOLEAN;
    v_hw_fixed_condition BOOLEAN;
BEGIN
    IF TG_TABLE_NAME = 'sample' THEN
        v_sample_ids := ARRAY[NEW.sample_id];
    ELSIF TG_OP = 'DELETE' THEN
        v_sample_ids := ARRAY[OLD.sample_id];
    ELSIF TG_OP = 'UPDATE'
          AND OLD.sample_id IS DISTINCT FROM NEW.sample_id THEN
        v_sample_ids := ARRAY[OLD.sample_id, NEW.sample_id];
    ELSE
        v_sample_ids := ARRAY[NEW.sample_id];
    END IF;

    FOREACH v_sample_id IN ARRAY v_sample_ids
    LOOP
        SELECT s.sample_type
        INTO v_sample_type
        FROM fiber.sample AS s
        WHERE s.sample_id = v_sample_id;

        -- 删除一个没有被其他记录引用的样本时，不再检查其组分。
        IF NOT FOUND THEN
            CONTINUE;
        END IF;

        SELECT
            COUNT(sc.material_id)::INTEGER,
            COALESCE(SUM(sc.proportion_pct), 0)::NUMERIC(7, 2),
            (COUNT(*) FILTER (WHERE m.material_code = 'SW'))::INTEGER,
            (COUNT(*) FILTER (WHERE m.material_code = 'HW'))::INTEGER,
            COALESCE(
                BOOL_AND(sc.proportion_pct > 0 AND sc.proportion_pct < 100),
                FALSE
            ),
            COALESCE(
                BOOL_AND(
                    sc.beating_revolutions = 14000
                    AND sc.beating_degree_sr = 41.0
                ) FILTER (WHERE m.material_code = 'SW'),
                FALSE
            ),
            COALESCE(
                BOOL_AND(
                    sc.beating_revolutions = 8000
                    AND sc.beating_degree_sr = 40.6
                ) FILTER (WHERE m.material_code = 'HW'),
                FALSE
            )
        INTO
            v_component_count,
            v_total,
            v_sw_count,
            v_hw_count,
            v_all_intermediate,
            v_sw_fixed_condition,
            v_hw_fixed_condition
        FROM fiber.sample_component AS sc
        JOIN fiber.material AS m
          ON m.material_id = sc.material_id
        WHERE sc.sample_id = v_sample_id;

        IF v_sample_type = 'softwood' THEN
            IF v_component_count <> 1
               OR v_total <> 100.00
               OR v_sw_count <> 1
               OR v_hw_count <> 0 THEN
                RAISE EXCEPTION
                    '针叶木纯浆样本 % 必须且只能包含一个100%%的SW组分',
                    v_sample_id
                    USING
                        ERRCODE = '23514',
                        CONSTRAINT = 'ck_sample_component_business_rule';
            END IF;

        ELSIF v_sample_type = 'hardwood' THEN
            IF v_component_count <> 1
               OR v_total <> 100.00
               OR v_sw_count <> 0
               OR v_hw_count <> 1 THEN
                RAISE EXCEPTION
                    '阔叶木纯浆样本 % 必须且只能包含一个100%%的HW组分',
                    v_sample_id
                    USING
                        ERRCODE = '23514',
                        CONSTRAINT = 'ck_sample_component_business_rule';
            END IF;

        ELSIF v_sample_type = 'blend' THEN
            IF v_component_count <> 2
               OR v_total <> 100.00
               OR v_sw_count <> 1
               OR v_hw_count <> 1
               OR NOT v_all_intermediate
               OR NOT v_sw_fixed_condition
               OR NOT v_hw_fixed_condition THEN
                RAISE EXCEPTION
                    '复配样本 % 必须包含SW和HW各一个组分，比例均在0与100之间且合计100%%；SW固定14000r/41°SR，HW固定8000r/40.6°SR',
                    v_sample_id
                    USING
                        ERRCODE = '23514',
                        CONSTRAINT = 'ck_sample_component_business_rule';
            END IF;
        END IF;
    END LOOP;

    RETURN NULL;
END
$function$;

-- 新建样本后，即使完全没有组分，也会在提交前失败。
CREATE CONSTRAINT TRIGGER ctrg_sample_components_on_sample
AFTER INSERT OR UPDATE OF sample_type
ON fiber.sample
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION fiber.trg_assert_sample_components();

-- 组分新增、修改或删除后，在事务最终状态检查相关样本。
CREATE CONSTRAINT TRIGGER ctrg_sample_components_on_component
AFTER INSERT OR UPDATE OR DELETE
ON fiber.sample_component
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION fiber.trg_assert_sample_components();

REVOKE ALL
    ON FUNCTION fiber.trg_assert_sample_components()
    FROM PUBLIC;

COMMIT;
