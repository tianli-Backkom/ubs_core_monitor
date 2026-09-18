const {test}=require('node:test');const assert=require('node:assert/strict');const M=require('../web/core.js');
const fs=require('node:fs'),path=require('node:path');
const batch=(number,e2e_ms,eligible=true,children=[])=>({number,url:`trigger/${number}`,e2e_ms,eligible,children,status:'failure'});
test('one representative per PR gives mean25 P9029',()=>{const a={batches:[batch(1,10),batch(2,30)]},b={batches:[batch(3,20)]};assert.deepEqual(M.aggregate([a,b]).e2e,{n:2,mean:25,p90:29});});
test('ties, exclusions, missing tasks and no valid batch',()=>{const task={kind:'x86',url:'x/1',result:'SUCCESS',association_valid:true,total_ms:100};const bs=[batch(1,10,true,[task]),batch(2,30),batch(3,30),batch(4,100,false)];assert.equal(M.metrics(bs).representative_batch_number,3);assert.equal(M.metrics(bs).x86.total_ms,null);assert.equal(M.metrics([]).e2e_ms,null);});
test('task values come from same representative and filters preserve batches',()=>{const task=t=>({kind:'x86',url:'x/'+t,result:'SUCCESS',association_valid:true,total_ms:t});const p={number:1,state:'open',batches:[batch(1,10,true,[task(100)]),batch(2,30,true,[task(20)])]};assert.equal(M.aggregate([p]).x86.total.mean,20);assert.equal(M.filterPRs([p],{state:'open'})[0],p);assert.equal(M.filterPRs([p],{state:'merged'}).length,0);assert.equal(M.metrics(p.batches).representative_batch_number,2);});
test('percentile, empty and CSV formula escaping',()=>{assert.equal(M.stats([0,100,200,300]).p90,270);assert.equal(M.stats([]).mean,null);assert.ok(M.csv([['=1+1','a"b']]).includes("'=1+1"));});
test('frontend matches every persisted PR representative',()=>{const s=require('../data/snapshot.json');for(const p of s.prs)assert.deepEqual(M.metrics(p.batches),p.metrics);});
test('CSV exporter is available to browser and Node callers',()=>{assert.equal(typeof M.saveCsv,'function');});
test('static Pages export downloads a Blob without posting to the local API',async()=>{
 let fetches=0,clicked=false,blob,urlRevoked;
 const env={location:{hostname:'tianli-backkom.github.io'},fetch:async()=>{fetches++;},Blob,URL:{createObjectURL:value=>(blob=value,'blob:csv'),revokeObjectURL:value=>{urlRevoked=value}},document:{createElement:()=>({click(){clicked=true}})}};
 const result=await M.saveCsv([['仓库','PR'],['openeuler/ubs-engine',1]],'pr-summary.csv',env);
 assert.equal(fetches,0);assert.equal(clicked,true);assert.equal(urlRevoked,'blob:csv');assert.equal(result.mode,'download');assert.match(await blob.text(),/openeuler\/ubs-engine/);
});
test('localhost export posts CSV to the local save endpoint',async()=>{
 let request;const env={location:{hostname:'localhost'},fetch:async(url,options)=>(request={url,options},{ok:true,json:async()=>({url:'/exports/a.csv',name:'a.csv'})})};
 const result=await M.saveCsv([['仓库'],['openeuler/ubs-engine']],'a.csv',env);
 assert.equal(request.url,'/api/export');assert.equal(request.options.method,'POST');assert.match(request.options.body,/openeuler\/ubs-engine/);assert.equal(result.mode,'saved');
});
test('dashboard routes every CSV download through the environment-aware exporter',()=>{const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');assert.match(source,/Metrics\.saveCsv\(rows,name\)/);});
test('SLA assessment identifies task bottlenecks and trigger-stage anomalies',()=>{
 const task=(kind,total_ms)=>({kind,url:kind+'/1',result:'SUCCESS',association_valid:true,total_ms});
 const dtSlow={number:1,url:'t/1',eligible:true,e2e_ms:2_500_000,status:'success',children:[task('dt',1_300_000)]};
 const triggerSlow={number:2,url:'t/2',eligible:true,e2e_ms:2_500_000,status:'success',children:[task('dt',60_000),task('arm',60_000),task('x86',60_000)]};
 assert.equal(M.assessPR({number:1,batches:[dtSlow]}).severity,'red');
 assert.equal(M.assessPR({number:1,batches:[dtSlow]}).bottleneck,'dt');
 const e2eRedTaskYellow={number:3,url:'t/3',eligible:true,e2e_ms:50_000_000,status:'success',children:[task('dt',17*60_000)]};
 assert.equal(M.assessPR({number:3,batches:[e2eRedTaskYellow]}).bottleneck,'trigger');
 assert.equal(M.assessPR({number:2,batches:[triggerSlow]}).bottleneck,'trigger');
});
test('SLA assessment ranks red exceptions before failures and excludes quality-only rows',()=>{
 const red={number:1,created_ms:1,batches:[{number:1,url:'r',eligible:true,e2e_ms:1_900_000,status:'success',children:[]}]};
 const failed={number:2,created_ms:2,batches:[{number:1,url:'f',eligible:true,e2e_ms:100_000,status:'failure',children:[]}]};
 const quality={number:3,created_ms:3,issues:['missing event'],batches:[]};
 const rows=M.prioritizeExceptions([failed,quality,red]);
 assert.deepEqual(rows.map(x=>x.pr.number),[1,2]);
 assert.equal(M.filterPRs([red,failed,quality],{alert:'quality'}).length,1);
 assert.equal(M.filterPRs([red,failed,quality],{alert:'failure'})[0],failed);
});
