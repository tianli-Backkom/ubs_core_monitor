"""Audit multi-repository snapshots, original timings, SQLite and JavaScript parity."""
import json
import math
import sqlite3
import statistics
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def summary(values):
    values = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0)
    return {'n': len(values), 'mean': statistics.mean(values) if values else None,
            'p90': statistics.quantiles(values, n=10, method='inclusive')[8] if len(values) > 1 else values[0] if values else None}


def close(actual, expected):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), (actual.keys(), expected.keys())
        for key in expected: close(actual[key], expected[key])
    elif isinstance(expected, (int, float)):
        assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-6), (actual, expected)
    else:
        assert actual == expected, (actual, expected)


def audit():
    index = json.loads((ROOT / 'data/repositories.json').read_text('utf-8'))
    assert (ROOT / 'data/repositories.json').read_bytes() == (ROOT / 'web/data/repositories.json').read_bytes()
    expected_names = {r['name'] for r in json.loads((ROOT / 'repositories.json').read_text('utf-8'))}
    assert len(index['repositories']) == 9
    assert {r['name'] for r in index['repositories']} == expected_names
    raw_jobs = {}
    for path in (ROOT / 'data/raw').glob('*.json'):
        raw = json.loads(path.read_text('utf-8'))
        body = raw['body']
        if '/injectedEnvVars/' in raw['url']:
            assert not (set(body) - {'eventType','eventAction','eventActionDetail','jobTriggerTime','prCreateTime','commentID','gitcodePullRequestId','gitcodeTargetBranch'})
        if isinstance(body, dict):
            for job in body.get('allBuilds', []): raw_jobs[job['url']] = job
            if 'timestamp' in body and 'duration' in body and 'url' in body: raw_jobs[body['url']] = body
    snapshots, included, reports = {}, [], []
    seen_batches = set()
    checked = 0
    with sqlite3.connect(ROOT / 'data/efficiency.sqlite') as db:
        assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
        for entry in index['repositories']:
            path = ROOT / 'data/repos' / (entry['name'] + '.json')
            if not path.exists():
                assert entry['status'] in ['failed', 'pending']
                reports.append({'repository': entry['repository'], 'status': entry['status'], 'prs': None, 'error': entry.get('error')})
                continue
            snap = json.loads(path.read_text('utf-8'))
            snapshots[entry['name']] = snap
            assert path.read_bytes() == (ROOT / 'web/data/repos' / path.name).read_bytes()
            repo, prs = entry['repository'], snap['prs']
            assert snap['meta']['repository'] == repo
            assert len(prs) == len({p['number'] for p in prs})
            if entry['status'] == 'success': assert len(prs) == snap['meta']['expected_prs']
            current = all(snap['meta'][k] == index[k] for k in ['start_ms', 'end_ms'])
            if current and entry['status'] in ['success', 'partial']: included.extend(prs)
            rows = {number: json.loads(payload) for number, payload in db.execute('select number,payload from prs where repository=?', (repo,))}
            assert set(rows) == {p['number'] for p in prs}
            for pr in prs:
                assert pr['repository'] == repo
                assert snap['meta']['start_ms'] <= pr['created_ms'] <= snap['meta']['end_ms']
                assert rows[pr['number']]['metrics'] == pr['metrics']
                candidates = [b for b in pr['batches'] if b['eligible']]
                representative = max(candidates, key=lambda b: (b['e2e_ms'], int(b['number']), b['url'])) if candidates else None
                m = pr['metrics']
                assert m['representative_batch_url'] == (representative['url'] if representative else None)
                assert m['representative_batch_number'] == (representative['number'] if representative else None)
                assert m['e2e_ms'] == (representative['e2e_ms'] if representative else None)
                for kind in ['x86', 'arm', 'dt']:
                    tasks = {j['url']: j for j in (representative['children'] if representative else []) if j['kind'] == kind and j.get('association_valid') and not j.get('building') and j.get('result') in ['SUCCESS', 'FAILURE', 'UNSTABLE']}
                    task = next(iter(tasks.values())) if len(tasks) == 1 else {}
                    for field in ['url', 'queue_ms', 'duration_ms', 'total_ms']: assert m[kind][field] == task.get(field)
                for batch in pr['batches']:
                    assert batch['url'] not in seen_batches
                    seen_batches.add(batch['url'])
                    stored = db.execute('select repository,pr,payload from batches where url=?', (batch['url'],)).fetchone()
                    assert stored[:2] == (repo, pr['number']) and json.loads(stored[2]) == batch
                    jobs = [batch['trigger']] + batch['children']
                    if batch['status'] == 'success': assert batch['complete'] and batch['children'] and all(j.get('result') == 'SUCCESS' and not j.get('building') for j in jobs)
                    if batch['eligible']:
                        assert batch['status'] in ['success', 'failure'] and batch['complete'] and not batch['cancelled']
                        assert batch['request_ms'] is not None
                        assert batch['e2e_ms'] == max(j['end_ms'] for j in jobs) - batch['request_ms'] >= 0
                    if batch['request_ms'] is None: assert batch['e2e_ms'] is None
                    trigger_path = batch['trigger']['url'].split('/job/', 1)[-1].rsplit('/', 2)[0].replace('/job/', '/')
                    for child in batch['children']:
                        if child.get('association_valid'):
                            assert any(c.get('upstreamBuild') == batch['number'] and c.get('upstreamProject') == trigger_path for c in child.get('causes', [])), child['url']
                    for job in jobs:
                        if job.get('total_ms') is not None: assert job['total_ms'] == job['queue_ms'] + job['duration_ms']
                        raw = raw_jobs.get(job['url'])
                        if raw and not job.get('building'):
                            assert (raw['timestamp'], raw['duration']) == (job['start_ms'], job['duration_ms'])
                            checked += 1
            reports.append({'repository': repo, 'status': entry['status'], 'current': current, 'prs': len(prs), 'states': dict(Counter(p['state'] for p in prs)), 'representatives': sum(p['metrics']['e2e_ms'] is not None for p in prs)})
    expected = {'e2e': summary([p['metrics']['e2e_ms'] for p in included])}
    for kind in ['x86', 'arm', 'dt']:
        expected[kind] = {field: summary([p['metrics'][kind][field + '_ms'] for p in included]) for field in ['queue', 'duration', 'total']}
    script = "const fs=require('fs'),m=require('./web/core.js'),i=JSON.parse(fs.readFileSync('data/repositories.json','utf8')),s={};for(const e of i.repositories){const p='data/repos/'+e.name+'.json';if(fs.existsSync(p))s[e.name]=JSON.parse(fs.readFileSync(p,'utf8'));}for(const v of Object.values(s))for(const p of v.prs){if(JSON.stringify(m.metrics(p.batches))!==JSON.stringify(p.metrics)){const assert=require('assert');assert.deepStrictEqual(m.metrics(p.batches),p.metrics);}}const rows=m.repositoryRows(i,s);process.stdout.write(JSON.stringify(m.aggregate(rows.flatMap(r=>r.prs))));"
    result = subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8')
    close(json.loads(result.stdout), expected)
    report = {'checks_passed': True, 'repositories': reports, 'included_prs': len(included), 'metrics': expected, 'raw_timing_records_checked': checked, 'batches': len(seen_batches)}
    (ROOT / 'data/validation-multi.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__': audit()
