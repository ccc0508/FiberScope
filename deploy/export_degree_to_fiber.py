# -*- coding: utf-8 -*-
"""
导出「打浆度 → 纤维」系数（分树种、二次 degree+degree²）。
y = b0 + b1*degree + b2*degree²  （原始尺度，推理不需 sklearn）
输出 deploy/degree_to_fiber_coefficients.json
"""
import argparse
import os, sys, json
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('training_root', help='Training project containing dataset/tabular and model experiment outputs')
parser.add_argument('output_dir', help='Destination directory for the exported coefficients')
args = parser.parse_args()
ROOT = args.training_root
df = pd.read_csv(os.path.join(ROOT,'dataset','tabular','beating_clean.csv'))
meta = json.load(open(os.path.join(ROOT,'dataset','tabular','meta.json'),encoding='utf-8'))
FIBER = meta['fiber_names']
OUTDIR = args.output_dir
os.makedirs(OUTDIR, exist_ok=True)

def cv_r2(X, y, repeats=3):
    X=np.asarray(X,float); y=np.asarray(y,float); s=[]
    for r in range(repeats):
        kf=KFold(5, shuffle=True, random_state=42+r); p=np.zeros_like(y)
        for tr,te in kf.split(X):
            m=make_pipeline(StandardScaler(), Ridge(alpha=1.0)); m.fit(X[tr],y[tr])
            p[te]=m.predict(X[te]).ravel()
        s.append(r2_score(y,p))
    return float(np.mean(s))

DEPLOY={}
for sp,nm,sid in [(0,'针叶木','softwood'),(1,'阔叶木','hardwood')]:
    sub=df[df.species==sp].reset_index(drop=True)
    d=sub['degree'].values.astype(float)
    X=np.column_stack([d, d**2])
    DEPLOY[sid]={'species_cn':nm,'n':int(len(sub)),
                 'degree_range':[round(float(d.min()),2), round(float(d.max()),2)],
                 'fiber':{}}
    for f in FIBER:
        y=sub[f].values.astype(float)
        m=make_pipeline(StandardScaler(), Ridge(alpha=1.0)); m.fit(X,y)
        sc=m.named_steps['standardscaler']; rd=m.named_steps['ridge']
        # 原始尺度：c1=coef1/scale1, c2=coef2/scale2, b0=intercept - c1*mean1 - c2*mean2
        c1=float(rd.coef_[0]/sc.scale_[0]); c2=float(rd.coef_[1]/sc.scale_[1])
        b0=float(rd.intercept_ - c1*sc.mean_[0] - c2*sc.mean_[1])
        r=cv_r2(X,y)
        DEPLOY[sid]['fiber'][f]={'intercept':round(b0,6),
                                 'coef_degree':round(c1,6),'coef_degree2':round(c2,6),
                                 'cv_r2':round(r,3),'reliable':bool(r>=0.40)}
        print(f"{nm} {f:<10} R²={r:+.2f} {'✅' if r>=0.4 else '❌'}")

path=os.path.join(OUTDIR,'degree_to_fiber_coefficients.json')
json.dump(DEPLOY, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
print('\n->', path)
