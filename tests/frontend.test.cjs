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
test('PR sorting has deterministic E2E, execution-count and creation orders',()=>{
 const p=(number,e2e,batches,created)=>({number,created_ms:created,batches:Array.from({length:batches},(_,i)=>({number:i+1,url:`t/${number}/${i}`,eligible:true,e2e_ms:e2e,children:[]}))});
 const slow=p(1,30,2,10),many=p(2,20,5,20),newer=p(3,20,1,30);
 assert.deepEqual(M.sortPRs([many,newer,slow],'e2e').map(x=>x.number),[1,3,2]);
 assert.deepEqual(M.sortPRs([slow,newer,many],'batches').map(x=>x.number),[2,1,3]);
 assert.deepEqual(M.sortPRs([slow,many,newer],'created').map(x=>x.number),[3,2,1]);
});
