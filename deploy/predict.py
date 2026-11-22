# -*- coding: utf-8 -*-
"""
deploy 预测脚本：读 model_coefficients.json，纯 numpy 计算（不需要 sklearn）。
用法：
  python predict.py 输入.csv 输出.csv
输入 CSV 需含：species（针叶木/阔叶木，或 0/1，或 softwood/hardwood）+ 12 个纤维指标列。
输出 CSV：每行预测 9 个纸张性能；若某指标超出训练范围，会在 warning 列标明。
"""
import os, sys, json
import numpy as np
import pandas as pd
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
COEF = json.load(open(os.path.join(HERE,'model_coefficients.json'), encoding='utf-8'))

SPECIES_ALIAS = {
    '针叶木':'softwood','softwood':'softwood','0':'softwood','0.0':'softwood',
    '阔叶木':'hardwood','hardwood':'hardwood','1':'hardwood','1.0':'hardwood',
}
def norm_species(v):
    return SPECIES_ALIAS[str(v).strip()]

def predict_record(rec: dict) -> dict:
    """rec: {species, 各纤维指标: 数值} -> {各性能预测: 数值, '_warnings': [...]}"""
    sid = norm_species(rec['species'])
    m = COEF[sid]
    out, warns = {}, []
    for target, t in m['targets'].items():
        xs = []
        for f in t['features']:
            if f not in rec or pd.isna(rec[f]):
                raise ValueError(f"缺少指标: {f}")
            x = float(rec[f]); xs.append(x)
            lo, hi = m['feature_ranges'][f]
            if x < lo - 1e-9 or x > hi + 1e-9:
                warns.append(f"{target}: {f}={x:.3g} 超出训练范围[{lo},{hi}]（外推，慎用）")
        z = t['intercept'] + float(np.dot(t['coef'], xs))
        out[target] = float(10**z) if t['log10'] else float(z)
    out['_warnings'] = warns
    return out

def predict_df(df: pd.DataFrame) -> pd.DataFrame:
    rows, warns_all = [], []
    for _, r in df.iterrows():
        p = predict_record(r.to_dict())
        w = p.pop('_warnings')
        rows.append(p); warns_all.append('; '.join(w))
    out = pd.DataFrame(rows)
    out['warning'] = warns_all
    return out

def main():
    if len(sys.argv) < 3:
        print('用法: python predict.py 输入.csv 输出.csv'); sys.exit(1)
    inp, outp = sys.argv[1], sys.argv[2]
    df = pd.read_csv(inp, encoding='utf-8-sig')
    if 'species' not in df.columns:
        raise ValueError('输入需含 species 列（针叶木/阔叶木 或 0/1）')
    pred = predict_df(df)
    keep = ['species']
    src = ['species'] if 'species' in df.columns else []
    pred = pd.concat([df[['species']].reset_index(drop=True), pred.reset_index(drop=True)], axis=1)
    pred.to_csv(outp, index=False, encoding='utf-8-sig')
    print(f'预测完成 -> {outp}  ({len(pred)} 行)')
    if pred['warning'].str.len().sum() > 0:
        print('注意：有外推警告，见 warning 列')

if __name__ == '__main__':
    main()
