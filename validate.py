"""Independent audit of real snapshot, raw timing records, and SQLite persistence."""
import sys
import json
import math
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

root=Path(__file__).resolve().parent
if (root/'data/repositories.json').exists():
    from validate_multi import audit
    audit()
    sys.exit(0)
s=json.loads((root/'data/snapshot.json').read_text('utf-8'))
prs=s['prs'];batches=[b for p in prs for b in p['batches']]
assert len(prs)==len({p['number'] for p in prs})==s['meta']['expected_prs']
assert len(batches)==len({b['url'] for b in batches})
assert all(s['meta']['start_ms']<=p['created_ms']<=s['meta']['end_ms'] for p in prs)
raw_by_url={}
for f in (root/'data/raw').glob('*.json'):
    r=json.loads(f.read_text('utf-8'));raw_by_url[r['url']]=r['body']
    if '/injectedEnvVars/' in r['url']:
        assert not (set(r['body'])-{'eventType','eventAction','eventActionDetail','jobTriggerTime','prCreateTime','commentID','gitcodePullRequestId','gitcodeTargetBranch'})
raw_jobs={}
for v in raw_by_url.values():
    if isinstance(v,dict):
        for j in v.get('allBuilds',[]):raw_jobs[j['url']]=j
checked=0
for b in batches:
    js=[b['trigger']]+b['children']
    if b['status']=='success':assert b['complete'] and b['children'] and all(j.get('result')=='SUCCESS' and not j.get('building') for j in js)
    if b['status']=='failure':assert any(j.get('result') not in ['SUCCESS',None] for j in js)
    if b['eligible']:
        assert not b['cancelled'] and b['request_ms'] is not None
        assert b['e2e_ms']==max(j['end_ms'] for j in js)-b['request_ms']>=0
    if b['request_ms'] is None:assert b['e2e_ms'] is None
    for j in js:
        if j.get('total_ms') is not None:assert j['total_ms']==j['queue_ms']+j['duration_ms']
        raw=raw_jobs.get(j['url'])
        if raw and not j.get('building'):
            assert raw['duration']==j['duration_ms']
            assert raw['timestamp']==j['start_ms']
            checked+=1
representatives=[]
for p in prs:
    candidates=[b for b in p['batches'] if b['eligible']]
    representative=sorted(candidates,key=lambda b:(b['e2e_ms'],int(b['number']),b['url']))[-1] if candidates else None
    m=p['metrics']
    assert m['representative_batch_url']==(representative['url'] if representative else None)
    assert m['representative_batch_number']==(representative['number'] if representative else None)
    assert m['e2e_ms']==(representative['e2e_ms'] if representative else None)
    if representative:representatives.append(m['e2e_ms'])
    for kind in ['x86','arm','dt']:
        tasks={j['url']:j for j in (representative['children'] if representative else []) if j['kind']==kind and j.get('association_valid') and not j.get('building') and j.get('result') in ['SUCCESS','FAILURE','UNSTABLE']}
        task=next(iter(tasks.values())) if len(tasks)==1 else {}
        for field in ['queue_ms','duration_ms','total_ms','url']:assert m[kind][field]==task.get(field)
assert (root/'web/data/snapshot.json').read_bytes()==(root/'data/snapshot.json').read_bytes()
with sqlite3.connect(root/'data/efficiency.sqlite') as db:
    assert db.execute('select count(*) from prs').fetchone()[0]==len(prs)
    assert db.execute('select count(*) from batches').fetchone()[0]==len(batches)
    assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
    for number,payload in db.execute('select number,payload from prs'):
        assert json.loads(payload)['metrics']==next(p['metrics'] for p in prs if p['number']==number)
report={'checks_passed':True,'representative_prs':len(representatives),'representative_mean_ms':statistics.mean(representatives),'representative_p90_ms':statistics.quantiles(representatives,n=10,method='inclusive')[8],'prs':len(prs),'pr_states':dict(Counter(p['state'] for p in prs)),'batches':len(batches),
    'batch_states':dict(Counter(b['status'] for b in batches)),'eligible_e2e':sum(b['eligible'] for b in batches),
    'cancelled':sum(b['cancelled'] for b in batches),'missing_request':sum(b['request_ms'] is None for b in batches),
    'trigger_success_but_batch_failure':sum(b['trigger'].get('result')=='SUCCESS' and b['status']=='failure' for b in batches),
    'raw_timing_records_checked':checked,'no_gate_prs':[p['number'] for p in prs if not p['batches']]}
(root/'data/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
