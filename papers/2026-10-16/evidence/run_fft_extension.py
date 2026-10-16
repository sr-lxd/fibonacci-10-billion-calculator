"""Pre-register and test the first request step predicted by source model."""
from pathlib import Path
import json
import run_boundary_followup as base
from model_fft_sizes import query
ROOT=Path(__file__).resolve().parent
EXE=base.OUT/'build'/'gmp_boundary_followup.exe'
base.OUT=ROOT/'experiments_20261016'/'staircase'
PLAN=[('msys2',67170304),('msys2',67170305),('msys2',67174400),('msys2',67174401),
      ('wheel231',67170304),('wheel231',67170305),('wheel221',67170304),('wheel221',67170305)]
def main():
    plan=[dict(dll_label=label,**query(s)) for label,s in PLAN]
    (base.OUT/'extension_predictions.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    rows=[]
    for label,s in PLAN:
        u=s//2;v=s-u;a=64*(u-1)+1;b=64*(v-1)+1
        p=base.OUT/'cases'/f'{label}_multiply_{a}_{b}'/'result.json'
        r=json.loads(p.read_text()) if p.exists() else base.case(EXE,label,a,b,'multiply')
        actual=r['wrapped_requests'][0]['signed64'] if r['wrapped_requests'] else None
        r.update(input_limb_sum=s,request_signed64=actual,source_model=query(s),prediction_matches=actual==query(s)['model_request_signed64'])
        rows.append(r)
        (base.OUT/'extension_summary.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    assert all(r['prediction_matches'] for r in rows)
    print('EXTENSION_DONE',[(r['dll_label'],r['input_limb_sum'],r['request_signed64']) for r in rows],flush=True)
if __name__=='__main__':main()
