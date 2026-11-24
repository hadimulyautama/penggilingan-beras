/* Uji murni penyandian; bukan fixture otoritas/peramban/izin produk. */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../app/web/static/kerangka-langsung.js',import.meta.url),'utf8');
const url='/barang-masuk';
function data(refs=[0,1,0]){
 return {versi:2,penyandian:'baris-1',cap:'cap-fixture',konteks:'ctx-fixture',sesi:'csrf-fixture',
  potongan:['<script src="/asset?v=x" nonce="fixture">α</script>\r\n','<h1>Nama & angka belum dibaca</h1>\n'],frames:{[url]:refs}};
}
function baca(registry,address=url,stock=null){
 const host={isConnected:true,dataset:{cap:'cap-fixture',konteks:'ctx-fixture'},textContent:JSON.stringify(registry)};
 const frame={dataset:{pindahKonteks:'ctx-fixture'}},sesi={dataset:{token:'csrf-fixture'}};
 let provider;
 const PINDAH={aturKerangkaLangsung:fn=>provider=fn};
 const document={getElementById:id=>id==='padi-kerangka-langsung'?host:id==='formulir-sesi'?sesi:id==='padi-stok-kerangka'?stock:null,
  querySelector:s=>s==='.bingkai'?frame:null,documentElement:{getAttribute:()=> 'cap-fixture'}};
 const sandbox={window:{PINDAH},PINDAH,document,URL,location:{href:'https://uji/kabar'},__joins:0,__parses:0};
 const context=vm.createContext(sandbox);
 vm.runInContext('const asli=Array.prototype.join;Array.prototype.join=function(...a){__joins++;return asli.apply(this,a);};',context);
 vm.runInContext('const parse=JSON.parse;JSON.parse=function(...a){__parses++;return parse.apply(this,a);};',context);
 vm.runInContext(source,context);
 return {result:provider({alamat:address,sebab:'push'}),joins:sandbox.__joins,parses:sandbox.__parses};
}

for(const address of ['/stok?tab=','/stok?pemilik=','/stok?tab=produk&tab=bahan',
 '/stok?tab=asing','/stok?pemilik=asing','/stok?lain=1','/stok-produk',
 '/stok?pemilik=jasa&pelanggan_id=0','/stok?pelanggan_id=2','/stok?cari='+'x'.repeat(201)]){
 test('URL di luar kontrak Stok tidak membentuk frame: '+address.slice(0,60),()=>{
  const value=baca(data(),address);assert.equal(value.result,null);assert.equal(value.joins,0);
 });
}
test('descriptor Stok terlalu panjang ditolak sebelum JSON.parse',()=>{
 const stock={isConnected:true,dataset:{cap:'cap-fixture',konteks:'ctx-fixture'},textContent:' '.repeat(1572865)};
 const value=baca(data(),'/stok',stock);
 assert.equal(value.result,null);assert.equal(value.joins,0);assert.equal(value.parses,1,'Hanya registry utama yang boleh diparse');
});

test('join mempertahankan tiap karakter, pengulangan, urutan, src dan nonce',()=>{
 const d=data(),{result,joins}=baca(d);
 assert.equal(result.versi,1,'Kontrak SDK publik tetap versi1');
 assert.equal(result.html,d.potongan[0]+d.potongan[1]+d.potongan[0]);
 assert.equal(result.alamat,url);assert.equal(joins,1);
});
for(const [name,mutate] of [
 ['indeks negatif',d=>d.frames[url]=[-1]],
 ['indeks lewat batas',d=>d.frames[url]=[2]],
 ['indeks pecahan',d=>d.frames[url]=[0.5]],
 ['indeks string',d=>d.frames[url]=['0']],
 ['indeks boolean',d=>d.frames[url]=[true]],
 ['indeks null',d=>d.frames[url]=[null]],
 ['rujukan bukan array',d=>d.frames[url]='0'],
 ['rujukan kosong',d=>d.frames[url]=[]],
 ['potongan bukan array',d=>d.potongan={}],
 ['potongan kosong',d=>d.potongan=[]],
 ['potongan bukan string',d=>d.potongan=[{}]],
 ['potongan string kosong',d=>d.potongan=['']],
 ['frame melebihi batas sebelum join',d=>{d.potongan=['x'.repeat(524289)];d.frames[url]=[0];}],
 ['jumlah rujukan melebihi batas',d=>d.frames[url]=Array(16385).fill(0)],
 ['versi lama',d=>d.versi=1],
 ['penyandian tak dikenal',d=>d.penyandian='other'],
 ['alamat tidak diterbitkan',d=>delete d.frames[url]],
 ]){
 test(name+' gagal tertutup tanpa join',()=>{
  const d=data();mutate(d);const {result,joins}=baca(d);
  assert.equal(result,null);assert.equal(joins,0);
 });
}
