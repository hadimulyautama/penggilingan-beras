import test from 'node:test';import assert from 'node:assert/strict';import {createRequire} from 'node:module';import fs from 'node:fs';
const require=createRequire(import.meta.url),core=require('../app/web/static/portal-detail-kerangka.js');
const program=fs.readFileSync(new URL('../app/web/static/kerangka-portal-detail-ui.js',import.meta.url),'utf8');
const data=JSON.parse(program.split('window.PadiKerangkaPortalDetailData=')[1].split(';\n')[0]);
const entry={kind:'giling',resource:'GIL-UJI',code:'GIL-UJI',heading:'Penggilingan gabah',title:'GIL-UJI',targets:['/pelanggan/proses-aktif/giling/GIL-UJI?tab_detail=hasil#panel-hasil']};
const cat={versi:1,sumber:data.sumber,cap:'synthetic-cap',akun:'7',sesi:'synthetic-only',address:'/pelanggan/jasa-saya',entries:[entry]};
test('active Giling, closed Giling and receipt keep distinct native read shapes',()=>{
 assert.equal(core.address(entry.targets[0],'https://p.invalid').hash,'#panel-hasil');
 assert.equal(core.address('/pelanggan/barang-masuk/12?tab_detail=tiket','https://p.invalid').tab,'tiket');
 assert.equal(core.address('/pelanggan/riwayat-giling/12?tab_detail=qc#rhs-panel-qc','https://p.invalid').kind,'giling-riwayat');
 assert.equal(core.address('/pelanggan/riwayat-giling/12?sebelum=-1','https://p.invalid').resource,'12');
 for(const p of ['/pelanggan/proses-aktif/sosoh/POL-1','/pelanggan/barang-keluar/1','/pelanggan/barang-masuk/1?buka=terima','/pelanggan/barang-masuk/1?pelanggan_id=0','/pelanggan/barang-masuk/1?tab_detail=qc#panel-qc','/pelanggan/proses-aktif/giling/G1?tab_detail=bahan#panel-hasil','/pelanggan/barang-masuk/1?tab_detail=%XX','/pelanggan/barang-masuk/1?tab_detail=qc&tab_detail=tiket'])assert.equal(core.address(p,'https://p.invalid'),null,p);
});
test('closed five-tab address cannot become active four-tab or action context',()=>{
 for(const p of ['/pelanggan/riwayat-giling/12?tab_detail=tiket','/pelanggan/riwayat-giling/12?tab_detail=qc#panel-qc',
 '/pelanggan/proses-aktif/giling/GIL-UJI?tab_detail=qc','/pelanggan/riwayat-giling/12?halaman_hasil=2',
 '/pelanggan/riwayat-giling/2147483648','/pelanggan/riwayat-giling/12?koreksi=berhasil'])assert.equal(core.address(p,'https://p.invalid'),null,p);
 const closed={...entry,kind:'giling-riwayat',resource:'12',targets:['/pelanggan/riwayat-giling/12']};
 assert.ok(core.valid({...cat,entries:[closed]},data,'synthetic-cap','7','synthetic-only'));
 for(const value of [{...closed,kind:'giling'},{...closed,resource:'13'},{...closed,targets:[entry.targets[0]]}])
  assert.equal(core.valid({...cat,entries:[value]},data,'synthetic-cap','7','synthetic-only'),false);
 const tabs=[...data.variants['giling-riwayat'].matchAll(/data-portal-detail-tab="([^"]+)"/g)].map(m=>m[1]);
 assert.deepEqual(tabs,['ringkasan','bahan','hasil','qc','riwayat']);
 assert.equal([...data.variants.giling.matchAll(/data-portal-detail-tab="([^"]+)"/g)].length,4);
});
test('catalog is bound to current private session/account/cap and exact program',()=>{
 assert.ok(core.valid(cat,data,'synthetic-cap','7','synthetic-only'));
 for(const[key,v]of[['cap','old'],['akun','8'],['sesi','old'],['sumber','0'.repeat(64)],['entries',[{...entry,resource:'OTHER'}]]])assert.equal(core.valid({...cat,[key]:v},data,'synthetic-cap','7','synthetic-only'),false,key);
 assert.equal(core.valid({...cat,scope_ids:[1,2]},data,'synthetic-cap','7','synthetic-only'),false);
});
test('no POST fetch cache or generated resource addresses live in detail presentation',()=>{
 const source=fs.readFileSync(new URL('../app/web/static/portal-detail-kerangka.js',import.meta.url),'utf8');
 assert.doesNotMatch(source,/fetch\(|sessionStorage|localStorage|\.submit\(|method\s*:\s*['"]POST/);
 assert.match(source,/e\.targets\.includes\(value\)/);assert.match(source,/getAttribute\('href'\)===value/);
 assert.match(source,/frame\.dataset\.portalDetailAddress!==current/);
 assert.match(source,/root\.querySelector\('\[data-portal-detail-heading\]'\)\.textContent=s\.e\.heading/);
});
