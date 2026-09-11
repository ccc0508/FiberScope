"""Audited indicator names and units, shared by all API consumers."""
from dataclasses import dataclass


def indicator(key, name, unit, group, scope, status='confirmed'):
    return dict(key=key, name=name, unit=unit, group=group, scope=scope, unit_status=status)


FIBER = [
    ('fiber_length_arithmetic_mm','纤维长度（算术平均）','mm'),
    ('fiber_length_weighted_mm','纤维长度（长度加权）','mm'),
    ('fiber_width_um','纤维宽度','μm'),('fiber_coarseness_mg_m','纤维粗度','mg/m'),
    ('kink_angle_deg','扭结角','°'),('kinked_fiber_pct','扭结纤维比例','%'),
    ('curved_fiber_pct','弯曲纤维比例','%'),('fibrillation_length_pct','分丝帚化长度比','%'),
    ('broken_fiber_pct','折断纤维比','%'),('fines_length_pct','细小纤维长度比','%'),
    ('fines_weighted_length_pct','细小纤维长度加权比','%'),('fines_area_pct','细小纤维面积比','%'),
]
PAPER = [
    ('basis_weight_g_m2','定量','g/m²'),('thickness_um','厚度','μm'),
    ('burst_index','耐破指数','kPa·m²/g'),('tear_index','撕裂指数','mN·m²/g'),
    ('tensile_index','抗张指数','N·m/g'),('zero_span_tensile','零距抗张强度','N/cm'),
    ('surface_roughness','表面粗糙度','ml/min'),('air_permeability','透气度','μm/(Pa·s)'),
    ('folding_endurance_raw','耐折度',None),
]
LENGTH = [
    ('length_0_2_0_3_pct','0.2–0.3 mm'),('length_0_3_0_45_pct','0.3–0.45 mm'),
    ('length_0_45_0_67_pct','0.45–0.67 mm'),('length_0_67_1_pct','0.67–1 mm'),
    ('length_1_1_5_pct','1–1.5 mm'),('length_1_5_2_24_pct','1.5–2.24 mm'),
    ('length_2_24_3_35_pct','2.24–3.35 mm'),('length_3_35_5_01_pct','3.35–5.01 mm'),
    ('length_5_01_7_5_pct','5.01–7.5 mm'),('length_gt_7_5_pct','>7.5 mm'),
]
INDICATORS = [indicator(k,n,u,'fiber',['core','recycled']) for k,n,u in FIBER]
INDICATORS += [indicator(k,n,u,'paper',['core'],
    'tentative' if k=='air_permeability' else 'unconfirmed' if k=='folding_endurance_raw' else 'confirmed') for k,n,u in PAPER]
INDICATORS += [indicator(k, f'长度分布 {n}', '%','distribution',['recycled']) for k,n in LENGTH]
INDICATORS += [indicator(k,n,u,'strength',['recycled']) for k,n,u in [
    ('tensile_strength_kn_m','抗张强度','kN/m'),('burst_strength_kpa','耐破强度','kPa'),('tear_strength_mn','撕裂强度','mN')]]
NOTES = ['空值保留为 null，百分比使用0—100口径。',
         '透气度单位暂定；耐折度单位未确认。',
         '再生纸浆数据块的处理条件未知；4条长度分布异常保留原值。',
         '图表展示对应关系，不代表因果关系；核心指数与再生纸浆强度不可混用。']


@dataclass(frozen=True)
class ViewSpec:
    view: str
    order: tuple[str, ...]
    filters: tuple[str, ...]
    expected: int
    scope: str | None = None


VIEWS = {
    'samples': ViewSpec('v_sample_overview',('canonical_code',),('sample_type','q','canonical_code'),61),
    'beating': ViewSpec('v_beating_analysis',('experiment_code','display_order'),('material_code','min_revolutions','max_revolutions'),52,'core'),
    'blends': ViewSpec('v_blend_analysis',('display_order',),(),11,'core'),
    'fiber-paper': ViewSpec('v_fiber_paper_analysis',('canonical_code',),('sample_type','canonical_code'),61,'core'),
    'recycled/cycles': ViewSpec('v_recycled_cycle_summary',('block_order','cycle_no'),('block_code','cycle_no'),47,'recycled'),
    'recycled/details': ViewSpec('v_recycled_cycle_detail',('block_order','cycle_no','replicate_no'),('block_code','cycle_no'),131,'recycled'),
    'quality': ViewSpec('v_recycled_data_quality',('source_row',),('block_code',),4),
    'lineage': ViewSpec('v_data_lineage',('source_id','usage_type','canonical_code','display_code','material_code'),('canonical_code','usage_type','file_name'),257),
}
