"""Pure, millisecond-based metrics. No network or UI dependencies."""
import math
import re
from datetime import datetime

def ms(value):
    if not value: return None
    if isinstance(value,(int,float)): return value
    return round(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000)

def summarize(values):
    a=sorted(v for v in values if isinstance(v,(int,float)) and math.isfinite(v) and v>=0)
    if not a: return {'n':0,'mean':None,'p90':None}
    pos=(len(a)-1)*.9; lo=int(pos); hi=math.ceil(pos)
    return {'n':len(a),'mean':sum(a)/len(a),'p90':a[lo]+(a[hi]-a[lo])*(pos-lo)}

def in_scope(pr,start,end):
    t=ms(pr.get('created_at'))
    return pr.get('base',{}).get('ref')=='master' and t is not None and start<=t<=end

def normalize_job(raw):
    actions=raw.get('actions',[])
    q=next((a for a in actions if 'waitingTimeMillis' in a),{})
    keys=['waitingTimeMillis','blockedTimeMillis','buildableTimeMillis']
    queue=sum(q[k] for k in keys) if all(isinstance(q.get(k),(int,float)) for k in keys) else None
    start=raw.get('timestamp');duration=raw.get('duration');running=raw.get('building',False) or raw.get('result') is None
    end=start+duration if start is not None and duration is not None and not running else None
    return dict(url=raw.get('url'),number=raw.get('number'),result=raw.get('result'),building=running,
        start_ms=start,duration_ms=duration if not running else None,end_ms=end,queue_ms=queue,
        total_ms=queue+duration if queue is not None and duration is not None and not running else None,
        scheduled_ms=start-queue if start is not None and queue is not None else None,
        causes=[c for a in actions for c in a.get('causes',[])],
        exporter=any('BuildInfoExporter' in a.get('_class','') for a in actions))

def classify(trigger,children,complete):
    jobs=[trigger]+children
    if any(j.get('building') for j in jobs): return 'running'
    if not complete or any(j.get('result') is None for j in jobs): return 'incomplete'
    if any(j['result']!='SUCCESS' for j in jobs): return 'failure'
    return 'success' if children else 'incomplete'

def measure_batch(trigger,children,request_ms,complete):
    status=classify(trigger,children,complete);jobs=[trigger]+children
    cancelled=any(j.get('result') in ['ABORTED','NOT_BUILT'] for j in jobs)
    ends=[j.get('end_ms') for j in jobs]
    end=max(ends) if ends and all(t is not None for t in ends) and complete else None
    e2e=end-request_ms if end is not None and request_ms is not None and end>=request_ms else None
    scheduled=trigger.get('scheduled_ms')
    ci=end-scheduled if end is not None and scheduled is not None and end>=scheduled else None
    return dict(status=status,cancelled=cancelled,end_ms=end,e2e_ms=e2e,jenkins_ms=ci,
        eligible=status in ['success','failure'] and e2e is not None)

def extract_events(pr,logs,comments):
    events=[dict(id='create',kind='create',time_ms=ms(pr['created_at']),sha=None,source='PR.created_at')]
    for row in logs:
        text=row.get('content','')
        if 'create merge request[' in text.lower():
            sha=re.search(r'commit_id:\s*([0-9a-f]{7,40})',text)
            if sha:events[0]['sha']=sha[1]
        elif 'created pull request' in text.lower() or '创建了 pull request' in text:
            sha=re.search(r'\b[0-9a-f]{8,40}\b',text)
            if sha:events[0]['sha']=sha[0]
        elif row.get('action')=='commit' and re.search(r'added \d+ commit|推送.*提交',text,re.I):
            shas=re.findall(r'<li>([0-9a-f]{7,40})\s*-',text)
            events.append(dict(id=str(row['id']),kind='push',time_ms=ms(row['created_at']),sha=shas[0] if len(shas)==1 else None,
                shas=shas,source='operate_logs',discussion_id=row.get('discussion_id')))
    for row in comments:
        if re.match(r'^\s*/(?:retest|check-pr|rebuild)(?:\s|$)',row.get('body',''),re.I):
            events.append(dict(id=str(row['id']),kind='retest',time_ms=ms(row['created_at']),sha=None,source='comments',discussion_id=row.get('discussion_id')))
    events.sort(key=lambda e:e['time_ms'])
    last=None
    for e in events:
        if e['kind']!='retest':last=e.get('sha')
        else:e['sha']=last
    return events

def match_event(env,events):
    typ=env.get('eventType');action=env.get('eventAction');at=ms(env.get('jobTriggerTime'))
    if typ=='note':
        candidates=[e for e in events if e['kind']=='retest' and str(env.get('commentID')) in [str(e.get('discussion_id')),str(e['id'])]]
    elif typ=='merge_request' and action=='open':candidates=[e for e in events if e['kind']=='create']
    elif typ=='merge_request' and action=='update' and env.get('eventActionDetail')=='source update' and at is not None:
        # Typed platform push event corroborates the trigger's own webhook timestamp.
        # Never select the nearest event across arbitrary intervals.
        candidates=[e for e in events if e['kind']=='push' and abs(e['time_ms']-at)<=5000]
    else:candidates=[]
    return candidates[0] if len(candidates)==1 else None

def task_kind(url):
    if '/x86-64/' in url:return 'x86'
    if '/aarch64/' in url:return 'arm'
    if '/DT/' in url:return 'dt'
    if '/pre-commit/' in url:return 'pre-commit'
    if '/check_issue_associate/' in url:return 'issue-check'
    return 'other'

def pr_metrics(batches):
    """One PR sample from its longest measurable terminal E2E batch; never borrow tasks."""
    valid = [b for b in batches if b.get('eligible') and isinstance(b.get('e2e_ms'), (int, float)) and b['e2e_ms'] >= 0]
    b = max(valid, key=lambda b: (b['e2e_ms'], int(b['number']), b['url']), default=None)
    out = dict(representative_batch_url=b['url'] if b else None,
               representative_batch_number=b['number'] if b else None,
               e2e_ms=b['e2e_ms'] if b else None)
    for kind in ['x86', 'arm', 'dt']:
        tasks = {j['url']: j for j in (b['children'] if b else []) if j['kind'] == kind and j.get('association_valid') and not j.get('building') and j.get('result') in ['SUCCESS', 'FAILURE', 'UNSTABLE']}
        # A category must identify exactly one task. Ambiguity stays empty.
        j = next(iter(tasks.values())) if len(tasks) == 1 else {}
        out[kind] = {f + '_ms': j.get(f + '_ms') for f in ['queue', 'duration', 'total']}
        out[kind]['url'] = j.get('url')
    return out
