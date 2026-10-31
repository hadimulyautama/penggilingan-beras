// Uji interaksi tanpa jaringan: isian, permintaan ganda, dan hasil tidak pasti.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app/web/static/perbaikan-pengiriman.js', 'utf8');

function halaman(fetch, sesi = true) {
  const message = {textContent:''}, button = {disabled:false};
  const f = {dataset:{url:'/api/actions/perbaikan-pengiriman/1/buka-ulang',log:'10'},
    elements:{alasan:{value:'Periksa jumlah fisik'},konfirmasi:{checked:true}},
    reportValidity:()=>true,querySelector:s=>s==='button'?button:message,
    addEventListener:(_,fn)=>{f.submit=()=>fn({preventDefault(){}});}};
  const window = {SESIFORM:{periksa:()=>sesi}};
  vm.runInNewContext(source,{document:{querySelector:()=>f,getElementById:()=>({dataset:{token:'uji'}})},
    fetch,window,SESIFORM:window.SESIFORM,AbortController,setTimeout,clearTimeout});
  return {f,message,button};
}

test('klik berulang hanya mengirim satu permintaan dan sukses tidak mengulang otomatis', async()=>{
  let calls=0,finish;
  const h=halaman(()=>{calls++;return new Promise(resolve=>{finish=resolve;});});
  const first=h.f.submit();await h.f.submit();assert.equal(calls,1);
  assert.equal(h.button.disabled,true);
  finish({ok:true,status:200,json:async()=>({pesan:'Verifikasi dibuka kembali'})});await first;
  await h.f.submit();assert.equal(calls,1);assert.match(h.message.textContent,/dibuka kembali/);
});

for(const status of [403,409,422])test('penolakan '+status+' mempertahankan alasan dan meminta pemeriksaan baru',async()=>{
  let calls=0;
  const h=halaman(async()=>{calls++;return {ok:false,status,json:async()=>({detail:'Sumber berubah'})};});
  await h.f.submit();await h.f.submit();assert.equal(calls,1);
  assert.equal(h.f.elements.alasan.value,'Periksa jumlah fisik');
  assert.match(h.message.textContent,/Sumber berubah/);assert.equal(h.button.disabled,true);
});

for(const mode of ['jaringan','server','json'])test('hasil tidak pasti: '+mode,async()=>{
  let calls=0;
  const h=halaman(async()=>{calls++;if(mode==='jaringan')throw Error('Terputus');
    return {status:mode==='server'?503:200,ok:mode!=='server',json:async()=>{throw Error('Terputus');}};});
  await h.f.submit();await h.f.submit();assert.equal(calls,1);
  assert.match(h.message.textContent,/belum dapat dipastikan/);
  assert.equal(h.f.elements.alasan.value,'Periksa jumlah fisik');
});

test('spasi dan sesi yang berubah tidak mengirim permintaan',async()=>{
  let calls=0;
  const h=halaman(async()=>{calls++;},false);
  await h.f.submit();assert.equal(calls,0);assert.match(h.message.textContent,/Sesi berubah/);
  h.f.elements.alasan.value='   ';await h.f.submit();assert.equal(calls,0);
  assert.match(h.message.textContent,/spasi/);
});
