const {test}=require('node:test');const assert=require('node:assert/strict');const M=require('../web/core.js');
test('trigger counts use distinct platform events and preserve unlinked requests',()=>{
 const p={events:[{id:'c',kind:'create'},{id:'p',kind:'push'},{id:'r',kind:'retest'},{id:'r',kind:'retest'}],batches:[{event_id:'c'},{event_id:'p'},{event_id:null}]};
 assert.deepEqual(M.triggerCounts(p),{create:1,push:1,retest:1,other:0,unlinked:1,unknownBatches:1});
});
test('failed wait surfaces cancellation even when longest representative succeeded',()=>{
 const p={batches:[{number:1,status:'failure',cancelled:true,e2e_ms:11021462},{number:2,status:'success',eligible:true,e2e_ms:12000000,children:[]}]};
 assert.equal(M.failedWait(p).number,1);assert.equal(M.failedWait({batches:[{status:'incomplete',e2e_ms:999}]}),null);
 assert.equal(M.failedWait({batches:[{status:'failure',e2e_ms:null}]}),null);
});

test('retest filter selects PRs without discarding any batches',()=>{const p={events:[{id:'r',kind:'retest'}],batches:[{status:'success'}]},q={events:[{id:'c',kind:'create'}],batches:[]};assert.deepEqual(M.filterPRs([p,q],{trigger:'retest'}),[p]);assert.equal(M.filterPRs([p],{trigger:'retest'})[0].batches,p.batches);});
