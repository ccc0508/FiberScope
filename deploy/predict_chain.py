# -*- coding: utf-8 -*-
"""
deploy 整链预测：打浆度(°SR) → 纤维形态 → 纸张性能
用法：python predict_chain.py 输入.csv 输出.csv
输入 CSV：species（针叶木/阔叶木 或 0/1）+ degree（打浆度 °SR）
输出 CSV：9 个纸张性能 + 12 个纤维预测 + 可靠性/越界提示
"""
import os, sys, json
import numpy as np
import pandas as pd
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
D2F = json.load(open(os.path.join(HERE,'degree_to_fiber_coefficients.json'), encoding='utf-8'))
F2P = json.load(open(os.path.join(HERE,'model_coefficients.json'), encoding='utf-8'))
ALIAS = {'针叶木':'softwood','softwood':'softwood','0':'softwood','0.0':'softwood',
         '阔叶木':'hardwood','hardwood':'hardwood','1':'hardwood','1.0':'hardwood'}
def sid(v): return ALIAS[str(v).strip()]

def predict_fiber(s, degree):
    m = D2F[s]
    out, warns = {}, []
    lo, hi = m['degree_range']
    if degree < lo - 1e-9 or degree > hi + 1e-9:
        warns.append(f"打浆度 {degree} 超出训练范围[{lo},{hi}]（外推，不可信）")
    for f, t in m['fiber'].items():
        y = t['intercept'] + t['coef_degree']*degree + t['coef_degree2']*degree**2
        out[f] = float(y)
        if not t['reliable']:
            out.setdefault('_unreliable', []).append(f)
    return out, warns

def predict_paper(s, fiber):
    out = {}
    for t, m in F2P[s]['targets'].items():
        xs = [fiber[f] for f in m['features']]
        z = m['intercept'] + float(np.dot(m['coef'], xs))
        out[t] = float(10**z) if m['log10'] else float(z)
    return out

def main():
    if len(sys.argv) < 3:
        print('用法: python predict_chain.py 输入.csv 输出.csv'); sys.exit(1)
    df = pd.read_csv(sys.argv[1], encoding='utf-8-sig')
    if not {'species','degree'} <= set(df.columns):
        raise ValueError('输入需含 species 和 degree 列')
    rows = []
    for _, r in df.iterrows():
        s = sid(r['species']); deg = float(r['degree'])
        fiber, fw = predict_fiber(s, deg)
        unreli = fiber.pop('_unreliable', [])
        paper = predict_paper(s, fiber)
        rec = {'species': r['species'], 'degree': deg}
        rec.update({f'预测_{k}': round(v,4) for k,v in paper.items()})
        rec.update({f'纤维_{k}': round(v,4) for k,v in fiber.items()})
        rec['不可靠纤维'] = ';'.join(unreli)
        rec['warning'] = ';'.join(fw)
        rows.append(rec)
    out = pd.DataFrame(rows)
    out.to_csv(sys.argv[2], index=False, encoding='utf-8-sig')
    print(f'整链预测完成 -> {sys.argv[2]}  ({len(out)} 行)')

if __name__ == '__main__':
    main()
