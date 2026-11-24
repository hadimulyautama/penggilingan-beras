/* Public blueprint boundary only; native permissions remain server-side. */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../app/web/static/kerangka-ui-runtime.js',import.meta.url),'utf8');
function api(mutate=()=>{}){
 const descriptor={versi:1,sumber:'fixture-source',cap:'cap',konteks:'ctx',sesi:'csrf',varians:{pengiriman:'pengiriman-operator',jasa:'jasa-admin'}};
 mutate(descriptor);
 const host={isConnected:true,dataset:{cap:'cap',konteks:'ctx'},textContent:JSON.stringify(descriptor)};
 const data={versi:1,sumber:'fixture-source',variants:{'pengiriman-operator':{path:'/barang-keluar',family:'pengiriman'},'jasa-admin':{path:'/jasa',family:'jasa',statuses:['','berjalan','selesai','dibatalkan','digabung']}}};
 let parsed=0;
 const sandbox={window:{PadiKerangkaUIData:data},document:{getElementById:()=>host},location:{href:'https://uji/kabar',origin:'https://uji'},URL,URLSearchParams,DOMParser:class{parseFromString(){parsed++;throw Error('Unexpected frame parse');}}};
 vm.runInNewContext(source,sandbox);
 return {make:address=>sandbox.window.PadiKerangkaUI.buat(address,null,'ctx','cap','csrf'),parsed:()=>parsed,data};
}
for(const url of ['/barang-keluar/1','/jasa/pelanggan/1','/barang-keluar?buka=ubah','/barang-keluar?status=perintah&status=selesai','/barang-keluar?sejak=2026-02-30','/barang-keluar?sejak=0000-01-01','/barang-keluar?pelanggan_id=0','/barang-keluar?q='+'x'.repeat(201),'/jasa?status=asing','/jasa?halaman=0','/jasa?cari=1&cari=2','/jasa?buka=catat','https://asing.invalid/jasa','/jasa#edit']){
 test('decline unsupported URL without creating DOM '+url.slice(0,65),()=>{const a=api();assert.equal(a.make(url),null);assert.equal(a.parsed(),0);});
}
for(const [name,mutate] of [['version',d=>d.versi=0],['source',d=>d.sumber='old'],['cap',d=>d.cap='old'],['company context',d=>d.konteks='other'],['session',d=>d.sesi='other'],['not granted',d=>d.varians={}],['unknown family',d=>d.varians.asing='other'],['wrong variant',d=>d.varians.jasa='pengiriman-operator']]){
 test('decline '+name+' without DOM or request',()=>{const a=api(mutate);assert.equal(a.make('/jasa'),null);assert.equal(a.parsed(),0);});
}
test('public structure immutable, not a source of authorization',()=>{const {data}=api();assert.ok(Object.isFrozen(data)&&Object.isFrozen(data.variants)&&Object.isFrozen(data.variants['jasa-admin'].statuses));});
