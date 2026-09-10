"""Read-only GitCode/Jenkins collector. Python 3.11+, standard library only."""
import argparse
import concurrent.futures as futures
import hashlib
import html
import json
import re
import uuid
from repository_store import save_database, publish_snapshot, publish_index, atomic_json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from metrics import ms, in_scope, normalize_job, extract_events, match_event, measure_batch, task_kind, pr_metrics

ROOT=Path(__file__).resolve().parent
CI='https://ci.openeuler.openatom.cn/'
CONFIG=json.loads((ROOT/'repositories.json').read_text('utf-8'))
ENV_KEYS=['eventType','eventAction','eventActionDetail','jobTriggerTime','prCreateTime','commentID','gitcodePullRequestId','gitcodeTargetBranch']
TREE='number,url,timestamp,duration,result,building,actions[_class,causes[shortDescription,upstreamBuild,upstreamProject,upstreamUrl],waitingTimeMillis,blockedTimeMillis,buildableTimeMillis]'

def canonical(url):
    p=urllib.parse.urlsplit(html.unescape(url));path=re.sub('/+','/',p.path)
    m=re.match(r'(.*/\d+)/',path+'/')
    return CI+m[1].lstrip('/')+'/' if p.hostname=='ci.openeuler.openatom.cn' and m else None

def links(text):
    return set(filter(None,(canonical(x) for x in re.findall(r'https://ci\.openeuler\.openatom\.cn/[^\s<>"\)]+',text))))

def downstream(console):
    found={}
    for path,num in re.findall(r'^(.+?) #(\d+) (?:started\.|completed\.)',console,re.M):
        parts=path.strip().split(' » ')
        if len(parts)<2:continue
        u=CI+''.join('job/'+urllib.parse.quote(p,safe='')+'/' for p in parts)+num+'/'
        if '/job/comment/' not in u and not job_path(u).startswith('Infra/docs/'):found[u]=True
    return set(found)

class Client:
    def __init__(self,cache,refresh=False,offline=False):
        self.cache=cache;cache.mkdir(parents=True,exist_ok=True)
        self.refresh=refresh;self.offline=offline;self.lock=threading.Lock();self.last=0;self.observed_at=[]
    def get(self,url,mutable=False,env=False):
        key=hashlib.sha256(url.encode()).hexdigest();p=self.cache/(key+'.json')
        if p.exists() and (self.offline or not mutable and not self.refresh or time.time()-p.stat().st_mtime<60):
            cached=json.loads(p.read_text('utf-8'));self.observed_at.append(cached['fetched_at'])
            return cached['body']
        if self.offline:raise RuntimeError('离线缓存缺失: '+url)
        for attempt in range(3):
            with self.lock:
                wait=max(0,.10-(time.monotonic()-self.last))
                if wait:time.sleep(wait)
                self.last=time.monotonic()
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'ubs-pr-efficiency/1.0','Accept':'application/json,text/plain,*/*'})
                with urllib.request.urlopen(req,timeout=40) as r:
                    body=r.read().decode('utf-8');ctype=r.headers.get('Content-Type','')
                if 'json' in ctype:body=json.loads(body)
                if env:
                    vals=body.get('envMap',{})
                    body={k:vals[k] for k in ENV_KEYS if k in vals}
                payload={'url':url,'fetched_at':datetime.now(timezone.utc).isoformat(),'body':body}
                self.observed_at.append(payload['fetched_at'])
                tmp=p.with_suffix('.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False),'utf-8');tmp.replace(p)
                return body
            except urllib.error.HTTPError as e:
                if e.code in [401,403,404]:raise
                if attempt==2:raise
                time.sleep(2**attempt)
            except (OSError,ValueError):
                if attempt==2:raise
                time.sleep(2**attempt)
    def pages(self,path,params=None):
        rows=[];seen=set()
        for page in range(1,1001):
            q=dict(params or {},page=page,per_page=100)
            data=self.get(path+'?'+urllib.parse.urlencode(q),mutable=True)
            if not isinstance(data,list):raise ValueError('API 返回非列表: '+path)
            if not data:break
            signature=tuple(str(x.get('id',x.get('number'))) for x in data)
            if signature in seen:raise ValueError('API 分页重复: '+path)
            seen.add(signature);rows.extend(data)
            if len(data)<100:break
        else:raise ValueError('超过分页上限: '+path)
        return rows

def catalog(client,path,start):
    url=CI+''.join('job/'+p+'/' for p in path.split('/'))
    result=[]
    for offset in range(0,20000,500):
        query='allBuilds['+TREE+']{'+str(offset)+','+str(offset+500)+'}'
        raw=client.get(url+'api/json?tree='+urllib.parse.quote(query,safe=''),mutable=True)
        batch=raw.get('allBuilds',[])
        result.extend(normalize_job(x) for x in batch if x.get('timestamp',0)>=start)
        if len(batch)<500 or min(x.get('timestamp',0) for x in batch)<start:break
    else:raise ValueError('Jenkins 历史构建超过安全分页上限')
    return result

def job_path(url):
    return '/'.join(urllib.parse.unquote(x) for x in urllib.parse.urlsplit(url).path.split('/')[2::2] if x)


def discover_jobs(client, api, selected, errors):
    """Discover from repository PR reports, never substitute repository names in paths."""
    comments_by_pr = {}
    paths = {}
    candidates = selected or client.pages(api+'/pulls', {'state':'all','base':'master','sort':'created','direction':'desc'})[:5]
    for p in candidates:
        try:
            comments = client.pages(api+f'/pulls/{p["number"]}/comments')
            comments_by_pr[p['number']] = comments
            for c in comments:
                if c.get('user', {}).get('login') != 'openeuler-ci-bot':continue
                for url in links(c.get('body', '')):
                    path = job_path(url)
                    if '/comment/' in '/'+path+'/' or path.startswith('Infra/docs/'):continue
                    paths.setdefault(path, dict(path=path,kind='trigger' if '/trigger/' in '/'+path+'/' else task_kind(url),evidence=[]))
                    if len(paths[path]['evidence']) < 3:paths[path]['evidence'].append(dict(pr=p['number'],comment_id=c.get('id'),build_url=url))
        except Exception as e:errors.append({'source':f'PR {p["number"]} comments discovery','reason':str(e)})
    return paths, comments_by_pr


def run(args, config=None, client=None):

    data=ROOT/'data';data.mkdir(exist_ok=True)
    config=config or CONFIG[0]
    repo=config['repository'];API='https://api.gitcode.com/api/v5/repos/'+repo
    client=client or Client(data/'raw',args.refresh,args.offline)
    observed_start=len(client.observed_at)
    end=datetime.fromisoformat(args.until) if args.until else datetime.now(timezone.utc)
    if end.tzinfo is None:end=end.replace(tzinfo=timezone(timedelta(hours=8)))
    start=end-timedelta(days=args.days);end_ms=ms(end.isoformat());start_ms=ms(start.isoformat())
    errors=[]
    print('读取 master PR 全部分页...',flush=True)
    raw_prs=client.pages(API+'/pulls',{'state':'all','base':'master','sort':'created','direction':'desc'})
    selected=[p for p in raw_prs if in_scope(p,start_ms,end_ms)]
    if args.limit:selected=selected[:args.limit]
    print(f'范围内 {len(selected)} PR / master 全部 {len(raw_prs)} PR',flush=True)
    mapping,comments_by_pr=discover_jobs(client,API,selected,errors)
    trigger_paths=[p for p,m in mapping.items() if m['kind']=='trigger']
    trigger_urls=[CI+''.join('job/'+urllib.parse.quote(x,safe='')+'/' for x in path.split('/')) for path in trigger_paths]
    jobs={}
    with futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending={pool.submit(catalog,client,path,start_ms):path for path in mapping}
        for f in futures.as_completed(pending):
            try:
                rows=f.result();mapping[pending[f]]['verified']=True;jobs.update({j['url']:j for j in rows});print('任务索引',pending[f],len(rows),flush=True)
            except Exception as e:errors.append({'source':pending[f],'reason':str(e)})
    trigger_by_pr={}
    for u,j in jobs.items():
        if not any(u.startswith(t) for t in trigger_urls):continue
        for c in j['causes']:
            m=re.search(r'PR (\d+) \[',c.get('shortDescription',''))
            if m:trigger_by_pr.setdefault(int(m[1]),set()).add(u)

    def one_pr(p):
        n=p['number'];issues=[]
        try:comments=comments_by_pr[n] if n in comments_by_pr else client.pages(API+f'/pulls/{n}/comments')
        except Exception as e:comments=[];issues.append('评论采集失败: '+str(e))
        try:logs=client.pages(API+f'/pulls/{n}/operate_logs')
        except Exception as e:logs=[];issues.append('操作日志采集失败: '+str(e))
        comments=[r for r in comments if ms(r.get('created_at')) is not None and ms(r['created_at'])<=end_ms]
        logs=[r for r in logs if ms(r.get('created_at')) is not None and ms(r['created_at'])<=end_ms]
        events=extract_events(p,logs,comments)
        reports={};triggers=set(trigger_by_pr.get(n,[]))
        for c in comments:
            if c.get('user',{}).get('login')!='openeuler-ci-bot':continue
            ls={u for u in links(c.get('body','')) if not job_path(u).startswith('Infra/docs/')};roots=[u for u in ls if any(u.startswith(t) for t in trigger_urls)]
            triggers.update(roots)
            if len(roots)==1 and '<table' in c.get('body',''):
                reports.setdefault(roots[0],set()).update(ls-set(roots))
        batches=[]
        for u in sorted(triggers,key=lambda x:int(x.rstrip('/').split('/')[-1])):
            problems=[];complete=True
            try:
                trigger=jobs.get(u) or normalize_job(client.get(u+'api/json?tree='+urllib.parse.quote(TREE,safe='')))
                if trigger.get('start_ms') and trigger['start_ms']>end_ms:continue
                if trigger.get('end_ms') and trigger['end_ms']>end_ms:
                    trigger=dict(trigger,building=True,result=None,end_ms=None,duration_ms=None,total_ms=None)
                env=client.get(u+'injectedEnvVars/api/json',env=True,mutable=trigger.get('building',False))
                if str(env.get('gitcodePullRequestId'))!=str(n):
                    issues.append('trigger 的 PR ID 不匹配: '+u);continue
                console=client.get(u+'consoleText',mutable=trigger.get('building',False))
                child_urls=downstream(console)
                expected=reports.get(u,set())
                if expected-child_urls:complete=False;problems.append('回写报告有子任务未在 trigger 日志中找到')
                child_urls |= expected
                children=[]
                for child_url in sorted(child_urls):
                    try:
                        child=dict(jobs.get(child_url) or normalize_job(client.get(child_url+'api/json?tree='+urllib.parse.quote(TREE,safe=''))))
                        if child.get('end_ms') and child['end_ms']>end_ms:
                            child.update(building=True,result=None,end_ms=None,duration_ms=None,total_ms=None)
                        valid=any(c.get('upstreamBuild')==trigger['number'] and c.get('upstreamProject')==job_path(u) for c in child['causes'])
                        child.update(kind=task_kind(child_url),association_valid=valid)
                        if not valid:complete=False;problems.append('子任务上游关联无法验证: '+child_url)
                        children.append(child)
                    except Exception as e:
                        complete=False;problems.append('子任务不可读取: '+child_url+' '+str(e))
                        children.append(dict(url=child_url,number=int(child_url.rstrip('/').split('/')[-1]),kind=task_kind(child_url),result=None,building=False,association_valid=False))
                if not re.search(r'^Finished: \w+',console,re.M) and not trigger.get('building'):
                    complete=False;problems.append('trigger 日志缺少结束标记')
                event=match_event(env,events)
                if event is None:problems.append('请求事件无法唯一关联；E2E 留空')
                if not children:problems.append('未发现子任务')
                if any(j.get('queue_ms') is None for j in children):problems.append('部分子任务缺失排队耗时')
                b=dict(url=u,number=trigger['number'],trigger=trigger,children=children,complete=complete,
                    event_id=event['id'] if event else None,event_type=event['kind'] if event else env.get('eventType','unknown'),
                    request_ms=event['time_ms'] if event else None,sha=event.get('sha') if event else None,
                    webhook_ms=ms(env.get('jobTriggerTime')),association='PR ID + webhook 类型/时间或评论 ID + 子任务 upstreamBuild',issues=problems)
                b.update(measure_batch(trigger,children,b['request_ms'],complete))
            except Exception as e:
                b=dict(url=u,number=int(u.rstrip('/').split('/')[-1]),trigger={'url':u},children=[],status='incomplete',eligible=False,cancelled=False,
                    e2e_ms=None,jenkins_ms=None,request_ms=None,event_id=None,event_type='unknown',sha=None,issues=['trigger 采集失败: '+str(e)])
            batches.append(b)
        used=[b['event_id'] for b in batches if b['event_id']]
        for b in batches:
            if b['event_id'] and used.count(b['event_id'])>1:
                b.update(eligible=False,e2e_ms=None,request_ms=None);b['issues'].append('同一请求关联多个 trigger，等待核验')
        if not batches:issues.append('未发现门禁批次')
        for e in events:
            e['batch_urls']=[b['url'] for b in batches if b['event_id']==e['id']]
            if not e['batch_urls']:issues.append('请求事件未关联 trigger: '+e['id'])
        state='merged' if p.get('merged_at') or p.get('state')=='merged' else ('open' if p.get('state')=='open' else 'closed')
        return dict(repository=repo,number=n,title=p['title'],state=state,author=p.get('user',{}).get('login',''),url=f'https://gitcode.com/{repo}/pull/{n}',
            created_ms=ms(p['created_at']),merged_ms=ms(p.get('merged_at')),closed_ms=ms(p.get('closed_at')),head_sha=p.get('head',{}).get('sha'),
            events=events,batches=batches,issues=issues,metrics=pr_metrics(batches),submission_count=sum(e['kind']!='retest' for e in events))

    prs=[]
    with futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending={pool.submit(one_pr,p):p['number'] for p in selected}
        for f in futures.as_completed(pending):
            try:prs.append(f.result());print(f'PR {pending[f]} 已采集 ({len(prs)}/{len(selected)})，{len(prs[-1]["batches"])} 批',flush=True)
            except Exception as e:errors.append({'source':f'PR {pending[f]}','reason':str(e)});print('PR ERROR',pending[f],str(e),flush=True)
    prs.sort(key=lambda p:p['created_ms'],reverse=True)
    for pr in prs:
        for source,issues in [(f'PR {pr["number"]}',pr['issues'])]+[(b['url'],b.get('issues',[])) for b in pr['batches']]:
            for reason in issues:
                if '采集失败' in reason or '不可读取' in reason:errors.append(dict(source=source,reason=reason))
    snapshot={'meta':dict(repository=repo,branch='master',start_ms=start_ms,end_ms=end_ms,
        collected_at=max(client.observed_at[observed_start:]) if client.observed_at[observed_start:] else None,generated_at=datetime.now(timezone.utc).isoformat(),days=args.days,expected_prs=len(selected),collected_prs=len(prs),errors=errors,
        limited=bool(args.limit),timezone='Asia/Shanghai',schema_version=3,job_mapping=list(mapping.values()),source='GitCode API v5 + Jenkins REST / trigger console / allowlisted webhook metadata'), 'prs':prs}
    save_database(snapshot)
    publish_snapshot(snapshot)
    print(json.dumps({'prs':len(prs),'batches':sum(len(p['batches']) for p in prs),'errors':errors},ensure_ascii=False),flush=True)
    return snapshot

def collect_many(args):
    end=datetime.fromisoformat(args.until) if args.until else datetime.now(timezone.utc)
    if end.tzinfo is None:end=end.replace(tzinfo=timezone(timedelta(hours=8)))
    args.until=end.isoformat();start_ms=ms((end-timedelta(days=args.days)).isoformat());end_ms=ms(args.until)
    client=Client(ROOT/'data/raw',args.refresh,args.offline)
    old_path=ROOT/'data/repositories.json'
    old=json.loads(old_path.read_text('utf-8')) if old_path.exists() else {}
    previous={r['name']:r for r in old.get('repositories',[])}
    entries=[dict(previous.get(c['name'],{}),name=c['name'],repository=c['repository']) for c in CONFIG]
    for entry in entries:
        if 'status' not in entry:entry.update(status='pending',snapshot=None,meta=None)
    for config,entry in zip(CONFIG,entries):
        if not args.all and config['name']!=args.repo:continue
        print('REPOSITORY '+config['name'],flush=True)
        try:
            snapshot=run(args,config,client)
            entry.update(status='partial' if snapshot['meta']['errors'] else 'success',error=None,snapshot='repos/'+config['name']+'.json',meta=snapshot['meta'])
        except Exception as e:
            entry.update(status='failed',error=str(e),attempted_at=datetime.now(timezone.utc).isoformat())
            print('REPOSITORY FAILED '+config['name']+': '+str(e),flush=True)
        publish_index(entries,start_ms,end_ms)
    return entries

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--days',type=int,default=30);p.add_argument('--until');p.add_argument('--workers',type=int,default=4)
    p.add_argument('--refresh',action='store_true');p.add_argument('--offline',action='store_true');p.add_argument('--limit',type=int,default=0,help='Only for diagnostic samples; marked on dashboard')
    group=p.add_mutually_exclusive_group();group.add_argument('--repo',choices=[c['name'] for c in CONFIG],default='ubs-engine');group.add_argument('--all',action='store_true')
    args=p.parse_args()
    if not 1<=args.workers<=8 or args.days<1:p.error('days>=1; workers 1..8')
    collect_many(args)
