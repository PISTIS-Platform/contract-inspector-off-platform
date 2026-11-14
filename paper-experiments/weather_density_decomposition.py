"""Per-column decomposition of the weather density sweep: python weather_density_decomposition.py DATA_DIR OUT_DIR."""
import sys, itertools
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd
sys.path.insert(0,'.')
import weather_density_sweep_metadata_experiment as W
from inspector.engine import SimilarityPipeline
from inspector.preprocessing import extract_path_values
from inspector import vocab
from inspector.real_datasets import load_weather_days
vocab.announce()
data=Path(sys.argv[1]); out=Path(sys.argv[2])
rdir=data/W.REAL_DATA_SOURCES['weather']['dirname']
days=load_weather_days(rdir,n_days=5,n_cells=5000,seed=W.SEED)
pipe=SimilarityPipeline(alpha=0.5,threshold=W.TAU,value_aware_only=True)
cols=W.UNIT_COLS_NATIVE_ORDER
rows=[];fields=[]
sc={f'cum{n}':cols[:n] for n in (1,3,6)}
sc.update({f'only_{c}':[c] for c in cols})
for t in itertools.combinations(cols,3): sc['tri_'+'+'.join(x.split('_')[0] for x in t)]=list(t)
for di,d in enumerate(days):
    for name,cs in sc.items():
        cl=W.convert_weather_value_only_metadata(d,cs)
        r=pipe.compare(d,cl)
        rows.append(dict(day=di,scenario=name,k=len(cs),jaccard=r.jaccard_score,value=r.value_score,combined=r.combined_score))
        if not name.startswith('tri_'):
            a=defaultdict(list)
            for p,s in r.field_similarities.items():
                a[p.split('.',1)[1] if '.' in p else p].append(s)
            pv1=dict(extract_path_values(d)); pv2=dict(extract_path_values(cl))
            same=defaultdict(list)
            for p in pv1:
                f=p.split('.',1)[1] if '.' in p else p
                same[f].append(pv1[p]==pv2.get(p))
            for f,v in a.items():
                fields.append(dict(day=di,scenario=name,field=f,mean_field_sim=float(np.mean(v)),frac_token_unchanged=float(np.mean(same[f])),n=len(v)))
R=pd.DataFrame(rows);F=pd.DataFrame(fields)
R.to_csv(out/'scores.csv',index=False);F.to_csv(out/'per_field.csv',index=False)
pd.set_option('display.width',220);pd.set_option('display.max_columns',30);pd.set_option('display.max_rows',200)
print('day 0, cumulative scenarios')
print(R[(R.day==0)&R.scenario.str.startswith('cum')])
print('cumulative per day'); print(R[R.scenario.str.startswith('cum')].pivot(index='day',columns='scenario',values='combined').round(4))
print('singles mean over 5 days'); print(R[R.scenario.str.startswith('only')].groupby('scenario')[['jaccard','value','combined']].agg(['mean','min','max']).round(4))
print('any-3 subsets, mean over 5 days'); t=R[R.scenario.str.startswith('tri')].groupby('scenario').combined.agg(['mean','min','max']).round(4).sort_values('mean');print(t)
print('per field, 6-of-6 scenario, mean over days'); print(F[F.scenario=='cum6'].groupby('field')[['mean_field_sim','frac_token_unchanged']].agg(['mean','min','max']).round(4))
print('per field by day: 6-of-6 unchanged share'); print(F[(F.scenario=='cum6')&F.field.isin(cols)].pivot(index='field',columns='day',values='frac_token_unchanged').round(3))
