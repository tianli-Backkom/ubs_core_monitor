(function(root){
  function stats(values){const a=values.filter(x=>typeof x==='number'&&Number.isFinite(x)&&x>=0).sort((a,b)=>a-b);if(!a.length)return {n:0,mean:null,p90:null};const p=(a.length-1)*.9,l=Math.floor(p),h=Math.ceil(p);return {n:a.length,mean:a.reduce((a,b)=>a+b,0)/a.length,p90:a[l]+(a[h]-a[l])*(p-l)};}
  function metrics(batches){
    const b=batches.filter(b=>b.eligible&&Number.isFinite(b.e2e_ms)&&b.e2e_ms>=0).sort((a,b)=>b.e2e_ms-a.e2e_ms||Number(b.number)-Number(a.number)||(a.url<b.url?1:a.url>b.url?-1:0))[0];
    const out={representative_batch_url:b?.url??null,representative_batch_number:b?.number??null,e2e_ms:b?.e2e_ms??null};
    for(const k of ['x86','arm','dt']){const tasks=new Map((b?.children||[]).filter(j=>j.kind===k&&j.association_valid&&!j.building&&['SUCCESS','FAILURE','UNSTABLE'].includes(j.result)).map(j=>[j.url,j]));const j=tasks.size===1?[...tasks.values()][0]:{};out[k]={url:j.url??null};for(const f of ['queue','duration','total'])out[k][f+'_ms']=j[f+'_ms']??null;}return out;
  }
  function aggregate(prs){const values=prs.map(p=>metrics(p.batches)),out={e2e:stats(values.map(v=>v.e2e_ms))};for(const k of ['x86','arm','dt']){out[k]={};for(const f of ['queue','duration','total'])out[k][f]=stats(values.map(v=>v[k][f+'_ms']));}return out;}
  function filterPRs(prs,{state='',query='',quality=''}={}){const q=query.toLowerCase().trim();return prs.filter(p=>(!state||p.state===state)&&(!q||[p.number,p.title,p.author,...p.batches.map(b=>b.sha||'')].join(' ').toLowerCase().includes(q))).filter(p=>!quality||(quality==='complete'?p.batches.length>0&&p.batches.every(b=>b.eligible)&&!(p.issues||[]).length:!p.batches.length||(p.issues||[]).length||p.batches.some(b=>!b.eligible)));}
  function repositoryRows(index,snapshots,state=''){return index.repositories.map(entry=>{const snapshot=snapshots[entry.name];const current=!!snapshot&&snapshot.meta.start_ms===index.start_ms&&snapshot.meta.end_ms===index.end_ms;const included=current&&['success','partial'].includes(entry.status);const prs=included?filterPRs(snapshot.prs,{state}):[];return {...entry,current,included,prs,metrics:aggregate(prs),counts:Object.fromEntries(['open','merged','closed'].map(k=>[k,prs.filter(p=>p.state===k).length]))};});}
  function csv(rows){return '\ufeff'+rows.map(row=>row.map(x=>{let s=x==null?'':String(x);if(/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"'}).join(',')).join('\r\n');}
  async function saveCsv(rows,name,env=root){
    const content=csv(rows),host=env.location?.hostname||'',local=['localhost','127.0.0.1','::1'].includes(host);
    if(local){
      const response=await env.fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,csv:content})});
      if(!response.ok)throw Error('HTTP '+response.status);
      return {mode:'saved',...(await response.json())};
    }
    const blob=new env.Blob([content],{type:'text/csv;charset=utf-8'}),url=env.URL.createObjectURL(blob),anchor=env.document.createElement('a');
    anchor.href=url;anchor.download=name;anchor.click();env.URL.revokeObjectURL(url);
    return {mode:'download',name};
  }
  const api={stats,metrics,aggregate,filterPRs,repositoryRows,csv,saveCsv};if(typeof module!=='undefined')module.exports=api;else root.Metrics=api;
})(typeof window!=='undefined'?window:globalThis);
