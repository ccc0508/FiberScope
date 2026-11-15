"""Coefficient-only inference. No training, database writes or ML runtime needed."""
from __future__ import annotations

import csv
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .catalog import INDICATORS, PAPER

MODEL_DIR = Path(__file__).resolve().parents[2] / 'deploy'
# Names in the delivered models differ from the audited database field names.
FIBER_NAMES = {
    '算数平均长': 'fiber_length_arithmetic_mm', '长度加权长': 'fiber_length_weighted_mm',
    '宽度': 'fiber_width_um', '粗度': 'fiber_coarseness_mg_m', '扭结角度': 'kink_angle_deg',
    '扭结纤维占比': 'kinked_fiber_pct', '弯曲': 'curved_fiber_pct',
    '分丝帚化长度比': 'fibrillation_length_pct', '折断纤维比': 'broken_fiber_pct',
    '细小纤维长度比': 'fines_length_pct', '细小纤维加权长度比': 'fines_weighted_length_pct',
    '细小纤维面积比': 'fines_area_pct',
}
PAPER_NAMES = {name: key for key, name, _ in PAPER}
INFO = {item['key']: item for item in INDICATORS}
SPECIES = {'针叶木': 'softwood', 'softwood': 'softwood', '0': 'softwood', '0.0': 'softwood',
           '阔叶木': 'hardwood', 'hardwood': 'hardwood', '1': 'hardwood', '1.0': 'hardwood'}
Number = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]


class SpeciesInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    species: Literal['softwood', 'hardwood']

    @field_validator('species', mode='before')
    @classmethod
    def normalize_species(cls, value):
        if isinstance(value, bool):
            raise ValueError('请选择针叶木或阔叶木')
        return SPECIES.get(str(value).strip(), value)


class FiberInput(SpeciesInput):
    features: dict[str, Number] = Field(max_length=12)


class DegreeInput(SpeciesInput):
    degree: Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0, le=100)]


def out_of_range(value, bounds):
    return value < bounds[0] - 1e-9 or value > bounds[1] + 1e-9


class PredictionEngine:
    def __init__(self, directory=MODEL_DIR):
        raw_paper = (directory / 'model_coefficients.json').read_bytes()
        raw_fiber = (directory / 'degree_to_fiber_coefficients.json').read_bytes()
        self.paper = json.loads(raw_paper)
        self.fiber = json.loads(raw_fiber)
        self.version = hashlib.sha256(raw_paper + raw_fiber).hexdigest()[:16]
        self.examples = {}
        with (directory / 'demo_input.csv').open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                self.examples.setdefault(SPECIES[row['species']],
                                         {key: float(row[name]) for name, key in FIBER_NAMES.items()})

    def required_features(self, species):
        return {FIBER_NAMES[name] for target in self.paper[species]['targets'].values()
                for name in target['features']}

    def metadata(self):
        species = []
        for key, model in self.paper.items():
            required = self.required_features(key)
            species.append({
                'key': key, 'name': model['species_cn'], 'sample_count': model['n'],
                'degree_range': self.fiber[key]['degree_range'],
                'features': [{'key': field, 'name': INFO[field]['name'], 'unit': INFO[field]['unit'],
                              'range': model['feature_ranges'][name], 'required': field in required}
                             for name, field in FIBER_NAMES.items()],
                'example': {'degree': 50, 'features': self.examples[key]},
            })
        return {'model_version': self.version, 'species': species,
                'notes': ['模型仅适用于针叶木和阔叶木纯浆，不适用于复配或再生纸浆。',
                          '训练样本为针叶木28个、阔叶木24个；超出训练范围时仅供外推参考。',
                          'R²来自交叉验证，不是准确率；低可靠性指标仅供参考。',
                          '打浆度整链尚无独立验证，单步R²不能代表整链精度。',
                          '透气度单位暂定；耐折度单位未确认。']}

    def predict(self, species, features=None, degree=None):
        chain = degree is not None
        model = self.paper[species]
        warnings, fiber_rows = [], []
        unreliable = set()
        degree_outside = False
        if chain:
            first = self.fiber[species]
            degree_outside = out_of_range(degree, first['degree_range'])
            warnings.append('整链预测未经独立验证，全部纸张结果仅供参考；表中R²仅评价实测纤维→纸张这一步。')
            if degree_outside:
                lo, hi = first['degree_range']
                warnings.append(f'打浆度 {degree:g} °SR 超出训练范围 [{lo:g}, {hi:g}]，属于外推。')
            features = {}
            for name, item in first['fiber'].items():
                key = FIBER_NAMES[name]
                value = item['intercept'] + item['coef_degree'] * degree + item['coef_degree2'] * degree ** 2
                features[key] = value
                if not item['reliable']:
                    unreliable.add(key)
                fiber_rows.append({'key': key, 'name': INFO[key]['name'], 'unit': INFO[key]['unit'],
                                   'value': value, 'cv_r2': item['cv_r2'],
                                   'model_reliable': item['reliable'],
                                   'in_range': not degree_outside and not out_of_range(value, model['feature_ranges'][name])})
            if unreliable:
                warnings.append('以下纤维预测可靠性不足，会影响依赖它们的纸张结果：' +
                                '、'.join(INFO[key]['name'] for key in features if key in unreliable) + '。')
        else:
            unknown = set(features) - set(FIBER_NAMES.values())
            if unknown:
                raise ValueError('存在无法识别的纤维指标，请使用模型表单中的指标。')
            missing = self.required_features(species) - features.keys()
            if missing:
                raise ValueError('请填写必需指标：' + '、'.join(INFO[key]['name'] for key in FIBER_NAMES.values() if key in missing))
            for key, value in features.items():
                unit = INFO[key]['unit']
                if (unit == '%' and value > 100) or (unit == '°' and value > 180):
                    raise ValueError(f'{INFO[key]["name"]}超出物理范围，请检查单位。')

        outside = {FIBER_NAMES[name] for name, bounds in model['feature_ranges'].items()
                   if FIBER_NAMES[name] in features and out_of_range(features[FIBER_NAMES[name]], bounds)}
        if outside:
            warnings.append('以下纤维指标超出实测纤维模型的训练范围：' +
                            '、'.join(INFO[key]['name'] for key in features if key in outside) + '；相关结果属于外推。')
        papers = []
        for name, item in model['targets'].items():
            keys = [FIBER_NAMES[f] for f in item['features']]
            try:
                value = item['intercept'] + sum(c * features[key] for c, key in zip(item['coef'], keys))
                if item['log10']:
                    value = 10 ** value
                if not math.isfinite(value):
                    raise OverflowError
            except OverflowError:
                raise ValueError('输入导致预测数值超出可计算范围，请检查指标与单位。') from None
            bad_inputs = [INFO[key]['name'] for key in keys if key in unreliable]
            extrapolated = [INFO[key]['name'] for key in keys if key in outside]
            in_range = not degree_outside and not extrapolated
            reference = chain or not item['reliable'] or not in_range or value < 0
            notes = []
            if not item['reliable']:
                notes.append('实测纤维模型的嵌套R²低于0.4。')
            if bad_inputs:
                notes.append('依赖低可靠性纤维：' + '、'.join(bad_inputs) + '。')
            if not in_range:
                notes.append('输入超出训练范围。')
            if value < 0:
                notes.append('预测出现非物理负值，不适用；保留原模型结果。')
            field = PAPER_NAMES[name]
            papers.append({'key': field, 'name': name, 'value': value,
                           'unit': INFO[field]['unit'], 'unit_status': INFO[field]['unit_status'],
                           'nested_r2': item['nested_r2'], 'model_reliable': item['reliable'],
                           'in_range': bool(in_range), 'reference_only': reference,
                           'unreliable_inputs': bad_inputs, 'notes': notes,
                           'status': '不适用' if value < 0 else '外推参考' if not in_range else
                           '整链参考' if chain else '仅供参考' if reference else '可参考'})
        return {'model_version': self.version, 'mode': 'degree' if chain else 'fiber',
                'species': species, 'species_name': model['species_cn'], 'sample_count': model['n'],
                'input': {'degree': degree} if chain else {'features': dict(features)},
                'paper': papers, 'fiber': fiber_rows, 'warnings': warnings}


@lru_cache(maxsize=1)
def get_engine():
    return PredictionEngine()


def engine():
    try:
        return get_engine()
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, '预测模型文件暂不可用，请联系管理员检查交付包。') from None


router = APIRouter(prefix='/api/v1/prediction', tags=['性能预测'])


@router.get('/metadata')
def metadata():
    return engine().metadata()


@router.post('/fiber')
def predict_fiber(body: FiberInput):
    try:
        return engine().predict(body.species, features=body.features)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/degree')
def predict_degree(body: DegreeInput):
    try:
        return engine().predict(body.species, degree=body.degree)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
