const {test}=require('node:test');const assert=require('node:assert/strict');const M=require('../web/core.js');
const pr=(n,value,state='open')=>({number:n,state,batches:[{eligible:true,e2e_ms:value,number:1,url:'t/'+value,children:[]}]});
const entries=['a','b','empty','stale','failed'].map(name=>({name,repository:'openeuler/'+name,status:name==='failed'?'failed':'success'}));
const index={start_ms:1,end_ms:2,repositories:entries};
const snap=(prs,start_ms=1)=>({meta:{start_ms,end_ms:2},prs});
const snapshots={a:snap([pr(1,30),pr(2,10,'merged')]),b:snap([pr(1,20)]),empty:snap([]),stale:snap([pr(1,999)],0),failed:snap([pr(1,999)])};
test('cross repo pools PR samples, preserves colliding IDs, excludes stale and failed',()=>{const rows=M.repositoryRows(index,snapshots);assert.equal(rows.length,5);assert.deepEqual(M.aggregate(rows.flatMap(r=>r.prs)).e2e,{n:3,mean:20,p90:28});assert.equal(rows.find(r=>r.name==='empty').included,true);assert.equal(rows.find(r=>r.name==='stale').included,false);assert.equal(rows.find(r=>r.name==='failed').included,false);});
test('state filter only selects PRs, keeps empty repository rows and representatives',()=>{const rows=M.repositoryRows(index,snapshots,'merged');assert.equal(rows.length,5);assert.equal(rows[0].prs[0],snapshots.a.prs[1]);assert.equal(rows[1].prs.length,0);assert.equal(M.aggregate(rows.flatMap(r=>r.prs)).e2e.mean,10);});
test('missing snapshot excluded; current partial snapshot included explicitly',()=>{const rows=M.repositoryRows({...index,repositories:[{name:'a',status:'partial'},{name:'missing',status:'success'}]},snapshots);assert.equal(rows[0].included,true);assert.equal(rows[1].included,false);});
