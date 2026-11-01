import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../app/web/static/portal-navigasi.js',import.meta.url),'utf8');
function setup(){const window={};vm.runInNewContext(source,{window,document:{getElementById(){return null}},Map});const pending=new Map(),views=[],statuses=[],redirects=[];let now=0,touched=0;
 const router=window.buatPengarahPortal({waktu:()=>now,sentuhan:()=>touched,ambil(url){if(!pending.has(url)){let resolve;const promise=new Promise(r=>resolve=r);pending.set(url,{promise,resolve})}return pending.get(url).promise},pasang(html,url,push){views.push({html,url,push});return true},status(...s){statuses.push(s)},utuh(url){redirects.push(url)}});
 return{router,pending,views,statuses,redirects,now(n){now=n},touch(){touched++}};}
const flush=()=>new Promise(r=>setImmediate(r));
test('halaman yang siap tampil sebelum jaringan menjawab',async()=>{const s=setup();s.router.ingat('/stok','lama');const p=s.router.pindah('/stok',true);assert.equal(s.views[0].html,'lama');s.pending.get('/stok').resolve('baru');await p;assert.deepEqual(s.views.map(v=>v.html),['lama','baru']);assert.deepEqual(s.views.map(v=>v.push),[true,false]);});
test('klik detail terbaru menang terhadap respons sidebar lama',async()=>{const s=setup();const a=s.router.pindah('/stok',true),b=s.router.pindah('/detail',true);s.pending.get('/detail').resolve('detail');await b;s.pending.get('/stok').resolve('stok');await a;assert.deepEqual(s.views.map(v=>v.html),['detail']);});
test('interaksi tidak dibuang oleh pembaruan cache',async()=>{const s=setup();s.router.ingat('/stok','lama');const p=s.router.pindah('/stok',true);s.touch();s.pending.get('/stok').resolve('baru');await p;assert.equal(s.views.length,1);assert.equal(s.statuses.at(-1)[0],'perubahan');await s.statuses.at(-1)[1]();await flush();assert.equal(s.views.at(-1).html,'baru');});
test('sesi tidak sah kembali ke login walaupun ada cache',async()=>{const s=setup();s.router.ingat('/stok','lama');const p=s.router.pindah('/stok',true);s.pending.get('/stok').resolve({login:true});await p;assert.deepEqual(s.redirects,['/pelanggan/masuk']);});
test('cache melewati 30 detik menunggu data baru',async()=>{const s=setup();s.router.ingat('/stok','lama');s.now(31000);const p=s.router.pindah('/stok',true);assert.equal(s.views.length,0);s.pending.get('/stok').resolve('baru');await p;assert.equal(s.views[0].html,'baru');});
test('cache dibatasi delapan halaman',async()=>{const s=setup();for(let i=0;i<9;i++)s.router.ingat('/'+i,'halaman'+i);const p=s.router.pindah('/0',true);assert.equal(s.views.length,0);s.pending.get('/0').resolve('baru');await p;});
test('POST membatalkan respons navigasi lama',async()=>{const s=setup();const p=s.router.pindah('/stok',true);s.router.bersihkan();s.pending.get('/stok').resolve('lama');await p;assert.equal(s.views.length,0);});
