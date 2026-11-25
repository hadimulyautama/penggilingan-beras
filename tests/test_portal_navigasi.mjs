import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../app/web/static/portal-navigasi.js',import.meta.url),'utf8');
function setup(bertahap=false){const window={};vm.runInNewContext(source,{window,document:{getElementById(){return null}},Map});const pending=new Map(),views=[],statuses=[],redirects=[],shells=[],failures=[];let now=0,touched=0;
 const router=window.buatPengarahPortal({waktu:()=>now,sentuhan:()=>touched,ambil(url){if(!pending.has(url)){let resolve;const promise=new Promise(r=>resolve=r);pending.set(url,{promise,resolve})}return pending.get(url).promise},kerangka(url,push){shells.push({url,push});return bertahap},gagal(url,ulang){failures.push({url,ulang})},pasang(html,url,push){views.push({html,url,push});return true},status(...s){statuses.push(s)},utuh(url){redirects.push(url)}});
 return{router,pending,views,statuses,redirects,shells,failures,now(n){now=n},touch(){touched++}};}
const flush=()=>new Promise(r=>setImmediate(r));
test('halaman yang siap tampil sebelum jaringan menjawab',async()=>{const s=setup();s.router.ingat('/stok','lama');const p=s.router.pindah('/stok',true);assert.equal(s.views[0].html,'lama');s.pending.get('/stok').resolve('baru');await p;assert.deepEqual(s.views.map(v=>v.html),['lama','baru']);assert.deepEqual(s.views.map(v=>v.push),[true,false]);});
test('klik detail terbaru menang terhadap respons sidebar lama',async()=>{const s=setup();const a=s.router.pindah('/stok',true),b=s.router.pindah('/detail',true);s.pending.get('/detail').resolve('detail');await b;s.pending.get('/stok').resolve('stok');await a;assert.deepEqual(s.views.map(v=>v.html),['detail']);});
test('pembaruan cache diterapkan otomatis setelah interaksi tanpa tombol pemberitahuan',async()=>{const s=setup();s.router.ingat('/stok','lama');const p=s.router.pindah('/stok',true);s.touch();s.pending.get('/stok').resolve('baru');await p;assert.equal(s.views.length,2);assert.equal(s.statuses.at(-1)[0],'selesai');assert.ok(!s.statuses.some(x=>x[0]==='perubahan'));assert.equal(s.views.at(-1).html,'baru');});
test('respons identik menjaga rincian terbuka tanpa pemberitahuan pembaruan',async()=>{const s=setup();s.router.ingat('/stok','sama');const p=s.router.pindah('/stok',true);s.touch();s.pending.get('/stok').resolve('sama');await p;assert.equal(s.views.length,1);assert.equal(s.statuses.at(-1)[0],'selesai');assert.ok(!s.statuses.some(s=>s[0]==='perubahan'));});
test('sesi tidak sah kembali ke login walaupun ada cache',async()=>{const s=setup();s.router.ingat('/stok','lama');const p=s.router.pindah('/stok',true);s.pending.get('/stok').resolve({login:true});await p;assert.deepEqual(s.redirects,['/pelanggan/masuk']);});
test('cache melewati 30 detik menunggu data baru',async()=>{const s=setup();s.router.ingat('/stok','lama');s.now(31000);const p=s.router.pindah('/stok',true);assert.equal(s.views.length,0);s.pending.get('/stok').resolve('baru');await p;assert.equal(s.views[0].html,'baru');});
test('cache dibatasi delapan halaman',async()=>{const s=setup();for(let i=0;i<9;i++)s.router.ingat('/'+i,'halaman'+i);const p=s.router.pindah('/0',true);assert.equal(s.views.length,0);s.pending.get('/0').resolve('baru');await p;});
test('POST membatalkan respons navigasi lama',async()=>{const s=setup();const p=s.router.pindah('/stok',true);s.router.bersihkan();s.pending.get('/stok').resolve('lama');await p;assert.equal(s.views.length,0);});
test('pembaruan otomatis memasang status terbaru tanpa menambah riwayat browser',async()=>{const s=setup();s.router.ingat('/proses','pengeringan');const p=s.router.perbarui('/proses',240);assert.equal(s.views.length,0);s.pending.get('/proses').resolve('pendinginan');await p;assert.equal(s.views.at(-1).html,'pendinginan');assert.equal(s.views.at(-1).push,false);assert.equal(s.statuses.at(-1)[0],'selesai');});
test('pembaruan otomatis tidak menimpa navigasi yang baru dipilih',async()=>{const s=setup();const p=s.router.perbarui('/proses',0);const nav=s.router.pindah('/detail',true);s.pending.get('/detail').resolve('detail');await nav;s.pending.get('/proses').resolve('lama');await p;assert.deepEqual(s.views.map(v=>v.html),['detail']);});
test('kegagalan pembaruan menjaga tampilan lama dan tidak reload berulang',async()=>{const s=setup();s.router.ingat('/proses','lama');const p=s.router.perbarui('/proses',0);s.pending.get('/proses').resolve(null);await p;assert.equal(s.views.length,0);assert.equal(s.redirects.length,0);assert.equal(s.statuses.at(-1)[0],'tertunda');});
test('pembaruan otomatis tidak berjalan ganda atau saat navigasi berlangsung',async()=>{const s=setup();const p=s.router.perbarui('/proses',0);await s.router.perbarui('/lain',0);assert.equal(s.pending.has('/lain'),false);s.pending.get('/proses').resolve('baru');await p;const nav=s.router.pindah('/detail',true);await s.router.perbarui('/proses',0);assert.equal(s.views.length,1);s.pending.get('/detail').resolve('detail');await nav;});
test('pembaruan otomatis sesi berakhir menuju login',async()=>{const s=setup();const p=s.router.perbarui('/proses',0);s.pending.get('/proses').resolve({login:true});await p;assert.deepEqual(s.redirects,['/pelanggan/masuk']);assert.equal(s.views.length,0);});
test('pergantian akun membatalkan respons pembaruan yang masih berjalan',async()=>{const s=setup();const p=s.router.perbarui('/proses',0);s.router.bersihkan();s.pending.get('/proses').resolve('akun lama');await p;assert.equal(s.views.length,0);});
test('pengeringan selesai mengikuti alamat tahap pendinginan yang sah',async()=>{const s=setup();const p=s.router.perbarui('/pengeringan',80);s.pending.get('/pengeringan').resolve({html:'pendinginan',url:'/pendinginan'});await p;assert.deepEqual(s.views,[{html:'pendinginan',url:'/pendinginan',push:false}]);});

test('portal baru menahan tampilan lama dan mendorong URL hanya saat hasil tiba',async()=>{const s=setup(true);const p=s.router.pindah('/baru',true);assert.deepEqual(s.shells,[{url:'/baru',push:true}]);assert.equal(s.views.length,0);s.pending.get('/baru').resolve('data');await p;assert.equal(s.views.length,1);assert.equal(s.views[0].push,true);});
test('kegagalan portal menyediakan percobaan ulang tanpa navigasi utuh atau kehilangan dorong',async()=>{const s=setup(true);const p=s.router.pindah('/baru',true);s.pending.get('/baru').resolve(null);await p;assert.equal(s.redirects.length,0);assert.equal(s.failures[0].url,'/baru');assert.equal(s.views.length,0);s.pending.delete('/baru');const retry=s.failures[0].ulang();assert.equal(s.shells.at(-1).push,true);s.pending.get('/baru').resolve('baru');await retry;assert.equal(s.views.length,1);assert.equal(s.views[0].html,'baru');assert.equal(s.views[0].push,true);});
test('akses yang ditolak tetap memakai respons server, bukan pesan putus jaringan',async()=>{const s=setup(true);const p=s.router.pindah('/rahasia',true);s.pending.get('/rahasia').resolve({utuh:'/rahasia'});await p;assert.deepEqual(s.redirects,['/rahasia']);assert.equal(s.failures.length,0);});

test('Back dan retry tidak menciptakan history push',async()=>{const s=setup(true);const p=s.router.pindah('/sebelum',false,90);s.pending.get('/sebelum').resolve(null);await p;s.pending.delete('/sebelum');const retry=s.failures[0].ulang();assert.equal(s.shells.at(-1).push,false);s.pending.get('/sebelum').resolve('data');await retry;assert.equal(s.views[0].push,false);});
test('respons gagal lama tidak membuka retry atau mengakhiri status pilihan baru',async()=>{const s=setup(true);const old=s.router.pindah('/lama',true),fresh=s.router.pindah('/baru',true);s.pending.get('/lama').resolve(null);await old;assert.equal(s.failures.length,0);assert.equal(s.views.length,0);assert.equal(s.statuses.at(-1)[0],'memuat');s.pending.get('/baru').resolve('baru');await fresh;assert.deepEqual(s.views,[{html:'baru',url:'/baru',push:true}]);});

function pendingDOM(inert=false,busy=null){
 const attributes=new Map(busy===null?[]:[['aria-busy',busy]]),header={children:[],appendChild(node){this.children.push(node);node.parent=this;}};
 const main={inert,innerHTML:'native old form and values',scrollTop:137,focusCalls:0,
  getAttribute(name){return attributes.has(name)?attributes.get(name):null;},
  setAttribute(name,value){attributes.set(name,value);},removeAttribute(name){attributes.delete(name);},
  focus(){this.focusCalls++;},querySelector(){throw Error('pending must not replace or inspect old content');}};
 const timers=new Map();let timerId=0;
 const document={title:'Native old title',querySelector(selector){assert.equal(selector,'.portal-top-identitas');return header;},
  createElement(tag){return{tag,children:[],attributes:{},setAttribute(name,value){this.attributes[name]=value;},
   addEventListener(name,callback){this[name]=callback;},appendChild(node){this.children.push(node);},
   remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}};}};
 const context={main,document,header,nonce:()=> 'same',sesi:'same',
  setTimeout(fn){const id=++timerId;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},
  segarkan(){throw Error('test must not request automatic retry');},
  history:{pushState(){throw Error('pending history changed');},replaceState(){throw Error('pending history changed');}},
  window:{dispatchEvent(){throw Error('pending navigation changed menu');}}};
 const first=source.indexOf('  function tandaiSibuk('),last=source.indexOf('  function ambil(');
 assert(first>0&&last>first);
 vm.runInNewContext('var pesan=null,timer=null,isiMenunggu=null,statusSibuk=null;'+source.slice(first,last)+
  ';globalThis.controls={kerangka,gagal,status,pulihkanIsi};',context);
 return Object.assign(context,{timers});
}

test('DOM pending menjaga isi judul posisi dan fokus, hanya main inert dan busy',()=>{
 const s=pendingDOM();assert.equal(s.controls.kerangka('/pelanggan/baru',true,0,'New title'),true);s.controls.status('memuat');
 assert.equal(s.main.innerHTML,'native old form and values');assert.equal(s.document.title,'Native old title');
 assert.equal(s.main.scrollTop,137);assert.equal(s.main.focusCalls,0);assert.equal(s.main.inert,true);assert.equal(s.main.getAttribute('aria-busy'),'true');
 assert.equal(s.header.children.length,0);assert.equal(s.timers.size,1);
 s.controls.kerangka();s.controls.status('memuat');s.controls.status('selesai');
 assert.equal(s.main.inert,false);assert.equal(s.main.getAttribute('aria-busy'),null);assert.equal(s.timers.size,0);
});
test('gagal tetap mempertahankan DOM dan mengembalikan inert serta aria-busy asli',()=>{
 for(const initial of [{inert:false,busy:'false'},{inert:true,busy:'true'},{inert:false,busy:null}]){
  const s=pendingDOM(initial.inert,initial.busy);let retries=0;
  s.controls.kerangka();s.controls.status('memuat');s.controls.gagal('/pelanggan/baru',()=>retries++);
  assert.equal(s.main.inert,initial.inert);assert.equal(s.main.getAttribute('aria-busy'),initial.busy);
  assert.equal(s.main.innerHTML,'native old form and values');assert.equal(s.document.title,'Native old title');
  assert.equal(s.header.children.length,1);const notice=s.header.children[0];
  assert.match(notice.textContent,/Tampilan sebelumnya tetap tersedia/);assert.equal(notice.children[0].textContent,'Coba lagi');
  notice.children[0].click();assert.equal(retries,1);assert.equal(s.timers.size,0);
 }
});
test('status selesai tidak menghapus aria-busy yang bukan miliknya dan nonce berubah tidak membekukan isi',()=>{
 const s=pendingDOM(false,'true');s.controls.status('selesai');assert.equal(s.main.getAttribute('aria-busy'),'true');
 s.nonce=()=> 'changed';assert.equal(s.controls.kerangka(),false);assert.equal(s.main.inert,false);
});
