// Actual SDK helpers, synthetic anchors only. Native browser/PG gates are separate.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const script=readFileSync(new URL('../hmu_tampilan/static/pindah.js',import.meta.url),'utf8');
const names=['alamatRingkasanJasa','rapikanRujukanJasa'];
const code=names.map(n=>{const start=script.indexOf('  function '+n+'(');assert.ok(start>=0);return script.slice(start,script.indexOf('\n  }\n',start)+5)}).join('\n');
const scope=vm.createContext({URL,location:{origin:'https://uji.local'}});vm.runInContext(code,scope);
function address(raw){return scope.alamatRingkasanJasa({querySelector(){return {dataset:{pindahAlamat:raw}}}})}
function normalize(href,target='/jasa/pelanggan/7?tab=ringkasan',matches=true){let value=href;scope.rapikanRujukanJasa({matches(){return matches},querySelectorAll(){return [{getAttribute(){return value},setAttribute(_,v){value=v}}]}},target);return value;}
test('only exact summary destination metadata opts in',()=>{for(const p of ['/jasa/pelanggan/7','/jasa/pelanggan/7?tab=ringkasan&pesanan_halaman=3&cari=asal'])assert.equal(address(p),p)});
for(const raw of ['/jasa/pelanggan/0','/jasa/pelanggan/2147483648','/jasa/pelanggan/7?tab=stok','/jasa/pelanggan/7?buka=tutup_jasa&nilai=8','/jasa/pelanggan/7?tab=ringkasan&tab=ringkasan','/jasa/pelanggan/7?company_id=8','/jasa/pelanggan/7#pesanan-pelanggan','https://other.invalid/jasa/pelanggan/7','/stok'])test('native fallback: '+raw,()=>assert.equal(address(raw),null));
test('matching return context is removed only on the comparison clone',()=>assert.equal(normalize('/barang-masuk?kembali_jasa='+encodeURIComponent('/jasa/pelanggan/7?tab=ringkasan')),'/barang-masuk'));
for(const [name,href] of [['different customer','/barang-masuk?kembali_jasa='+encodeURIComponent('/jasa/pelanggan/8?tab=ringkasan')],['duplicate','/barang-masuk?kembali_jasa=x&kembali_jasa=x'],['foreign shortcut','https://other.invalid/barang-masuk?kembali_jasa='+encodeURIComponent('/jasa/pelanggan/7?tab=ringkasan')],['fragment','/barang-masuk?'+new URLSearchParams({kembali_jasa:'/jasa/pelanggan/7?tab=ringkasan'})+'#x']])test(name+' is not normalized',()=>assert.equal(normalize(href),href));
test('other query parts survive so a changed scope still fails equality',()=>assert.equal(normalize('/barang-masuk?company_id=8&'+new URLSearchParams({kembali_jasa:'/jasa/pelanggan/7?tab=ringkasan'})),'/barang-masuk?company_id=8'));
test('sidebar and non-summary comparisons remain strict',()=>{const h='/barang-masuk?'+new URLSearchParams({kembali_jasa:'/jasa/pelanggan/7?tab=ringkasan'});assert.equal(normalize(h,null),h);assert.equal(normalize(h,undefined,false),h)});
