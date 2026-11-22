# -*- coding: utf-8 -*-
"""
导出部署用「原始尺度」线性系数（不依赖 sklearn 推理）。
对每个树种 × 每个目标：取 exp13 选出的 k* 指标，在全部该树种样本上重拟合 Ridge(alpha=1)，
把标准化系数换算回原始尺度：y = intercept_raw + sum(coef_raw_j * x_j)。
输出 deploy/model_coefficients.json
"""
import argparse
import os, sys, json
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('training_root', help='Training project containing dataset/tabular and model experiment outputs')
parser.add_argument('output_dir', help='Destination directory for the exported coefficients')
args = parser.parse_args()
ROOT = args.training_root
df = pd.read_csv(os.path.join(ROOT,'dataset','tabular','beating_clean.csv'))
meta = json.load(open(os.path.join(ROOT,'dataset','tabular','meta.json'),encoding='utf-8'))
FIBER = meta['fiber_names']; LOG = set(meta['log_targets'])
exp13 = pd.read_csv(os.path.join(ROOT,'models','exp13','per_species_minimal.csv'))
nested = pd.read_csv(os.path.join(ROOT,'models','exp14','nested_per_species.csv'))
nested_map = {(r['species'], r['target']): float(r['nested_r2']) for _, r in nested.iterrows()}
OUTDIR = args.output_dir
os.makedirs(OUTDIR, exist_ok=True)

DEPLOY = {}
for sp, nm, sid in [(0,'针叶木','softwood'),(1,'阔叶木','hardwood')]:
    sub = df[df.species==sp].reset_index(drop=True)
    rng = {f: [round(float(sub[f].min()),4), round(float(sub[f].max()),4)] for f in FIBER}
    DEPLOY[sid] = {'species_cn': nm, 'n': int(len(sub)),
                   'feature_ranges': rng, 'targets': {}}
    for _, row in exp13[exp13.species==nm].iterrows():
        t = row['target']
        feats = [s.strip() for s in str(row['k_star_feats']).split('+')]
        assert all(f in FIBER for f in feats), feats
        y = sub[t].astype(float).values
        yfit = np.log10(np.clip(y,1e-3,None)) if t in LOG else y
        X = sub[feats].values.astype(float)
        pipe = make_pipeline(StandardScaler(), Ridge(alpha=1.0)); pipe.fit(X, yfit)
        sc = pipe.named_steps['standardscaler']; rd = pipe.named_steps['ridge']
        coef_raw = rd.coef_ / sc.scale_
        intercept_raw = rd.intercept_ - float(np.sum(rd.coef_ * sc.mean_ / sc.scale_))
        DEPLOY[sid]['targets'][t] = {
            'features': feats,
            'coef': [round(float(c),6) for c in coef_raw],
            'intercept': round(intercept_raw,6),
            'log10': bool(t in LOG),
            'k': int(row['k_star']),
            'cv_r2_selected': round(float(row['k_star_r2']),3),   # 挑选后(乐观)
            'nested_r2': round(nested_map.get((nm, t), float('nan')),3),  # 嵌套(诚实)
            'reliable': bool(nested_map.get((nm, t), -9) >= 0.40),       # 诚实R²≥0.4才算可信
        }
        print(f"{nm} {t}: k={int(row['k_star'])} CV R²={row['k_star_r2']:+.2f} | {feats}")

path = os.path.join(OUTDIR,'model_coefficients.json')
json.dump(DEPLOY, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
print('\n->', path)
