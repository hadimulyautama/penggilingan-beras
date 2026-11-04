import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
const src=fs.readFileSync(new URL('../app/web/static/penerimaan-ringkas.js',import.meta.url),'utf8');
const code=src.slice(src.indexOf('  // Refresh QC saja:'),src.indexOf('  function openFragment()'));
function setup(){
 const qc={innerHTML:'QC lama'},status={innerHTML:'status lama'},note={hidden:true,textContent:''},host={draft:'karung 123'},state={dirty:true,inflight:false,uncertain:false,forms:{x:{jumlah_karung:'123'}}};
 const nextQC={innerHTML:'QC baru'},nextStatus={innerHTML:'status baru'};
 const fresh={dataset:{tiket:'24',actor:'2:operator:g2'},querySelector:s=>s==='#terima-panel-qc'?nextQC:s==='[data-qc-penerimaan-status]'?nextStatus:null};
 const root={isConnected:true,dataset:{tiket:'24',actor:'2:operator:g2'},querySelector:s=>s==='#terima-panel-qc'?qc:s==='[data-qc-penerimaan-status]'?status:s==='[data-qc-refresh-status]'?note:null};
 let resolve;const view={fields:[{value:'jangan disalin'}],details:new Map([['qc',true]])};
 const c={root,state,host,busy:false,checked:null,location:{pathname:'/barang-masuk/24',search:''},session(){c.sessions++;},sessions:0,requests:0,window:{KEADAAN_BACA:{ambil:()=>view,tukar:(target,next)=>{target.innerHTML=next.innerHTML;},pulihkan:(_r,s)=>{assert.equal(s.fields.length,0);c.restores++;}}},restores:0,DOMParser:class{parseFromString(){return {querySelector:()=>fresh};}},AbortController,setTimeout,clearTimeout,fetch:()=>{c.requests++;return new Promise(r=>resolve=r);}};
 vm.runInNewContext(code,c);
 return {c,root,qc,status,note,host,state,view,fresh,nextQC,nextStatus,resolve:(opts={})=>resolve({ok:true,redirected:false,text:async()=>'',...opts})};
}
test('Hanya QC/status berubah; draf dan formulir tidak dirender ulang',async()=>{const s=setup();const state=JSON.stringify(s.state),host=s.host;const p=s.root.pfReadRefresh();s.resolve();assert.equal(await p,true);assert.equal(s.qc.innerHTML,'QC baru');assert.equal(s.status.innerHTML,'status baru');assert.equal(JSON.stringify(s.state),state);assert.equal(s.host,host);assert.equal(s.c.restores,1);assert.equal(s.c.sessions,2);});
for(const flag of ['busy','inflight','uncertain','checked'])test(flag+' menahan refresh',async()=>{const s=setup();if(['inflight','uncertain'].includes(flag))s.state[flag]=true;else s.c[flag]=true;assert.equal(await s.root.pfReadRefresh(),false);assert.equal(s.c.requests,0);});
test('Permintaan bersamaan hanya satu fetch',async()=>{const s=setup();const p=s.root.pfReadRefresh();assert.equal(await s.root.pfReadRefresh(),false);s.resolve();assert.equal(await p,true);assert.equal(s.c.requests,1);});
test('Simpan dimulai saat fetch: tidak memasang data',async()=>{const s=setup();const p=s.root.pfReadRefresh();s.state.inflight=true;s.resolve();assert.equal(await p,false);assert.equal(s.qc.innerHTML,'QC lama');});
test('Navigasi saat fetch tidak menyentuh halaman baru',async()=>{const s=setup();const p=s.root.pfReadRefresh();s.c.location.pathname='/barang-masuk/12';s.resolve();assert.equal(await p,false);assert.equal(s.qc.innerHTML,'QC lama');});
for(const key of ['actor','tiket'])test('Konteks '+key+' berubah ditolak',async()=>{const s=setup();s.fresh.dataset[key]='lain';const p=s.root.pfReadRefresh();s.resolve();assert.equal(await p,false);assert.equal(s.qc.innerHTML,'QC lama');assert.equal(s.note.hidden,false);});
for(const opts of [{ok:false},{redirected:true}])test('HTTP gagal/redirect mempertahankan QC lama',async()=>{const s=setup();const p=s.root.pfReadRefresh();s.resolve(opts);assert.equal(await p,false);assert.equal(s.qc.innerHTML,'QC lama');assert.equal(s.note.hidden,false);});
test('Rincian hilang tidak dianggap QC kosong',async()=>{const s=setup();s.fresh.querySelector=()=>null;const p=s.root.pfReadRefresh();s.resolve();assert.equal(await p,false);assert.equal(s.qc.innerHTML,'QC lama');});
test('Sesi berubah saat fetch tidak memasang data',async()=>{const s=setup();s.c.session=()=>{if(++s.c.sessions>1)throw Error('sesi');};const p=s.root.pfReadRefresh();s.resolve();assert.equal(await p,false);assert.equal(s.qc.innerHTML,'QC lama');});
test('Root sudah terlepas tidak fetch',async()=>{const s=setup();s.root.isConnected=false;assert.equal(await s.root.pfReadRefresh(),false);assert.equal(s.c.requests,0);});

test('Jangkar baris tabel tanpa identitas tidak dicocokkan ke baris lain',async()=>{const s=setup();s.view.anchor={key:'TR:',top:90};const p=s.root.pfReadRefresh();s.resolve();assert.equal(await p,true);assert.equal(s.view.anchor,null);});
