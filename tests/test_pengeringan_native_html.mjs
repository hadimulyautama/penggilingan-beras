import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {descriptor,restoreTab}=require('../app/web/static/pengeringan-native-html.js');
const {validPackage,validCatalog,state}=require('../app/web/static/kerangka-pengeringan-ui-runtime.js');
const origin='https://fixture.invalid',source='a'.repeat(64),digest='b'.repeat(64);
const data={versi:1,sumber:source,variants:{pengeringan:{html:''},pendinginan:{html:''}}};
function envelope(){return {versi:1,cap:'cap',konteks:'context',sesi:'session',sumber:source,sumber_sha256:digest,entries:[{alamat:'/proses-aktif/pengeringan/LOT',kode:'LOT',fase:'pengeringan',label:'Pengeringan aktif'}]};}
const binding={cap:'cap',context:'context',token:'session',source,digest};
for(const phase of ['pengeringan','pendinginan'])test('exact '+phase+' address and native default tab',()=>{
 const address='/proses-aktif/'+phase+'/LOT-1?halaman_ukur=2';
 assert.equal(descriptor(address,origin).tab,'pengukuran');
 assert.equal(state(address,origin).tab,'pengukuran');
 assert.equal(descriptor(address,origin).phase,phase);
 assert.equal(state('/proses-aktif/'+phase+'/LOT?tab_detail=bahan&halaman_ukur=2',origin).tab,'bahan');
});
for(const suffix of ['?buka=','?buka=kadar_air','?nilai=','?tenant_id=9','?tab_detail=bahan&tab_detail=riwayat','?halaman_jeda=0','?halaman_dingin=-1','?kembali_kerja=%XX','?kembali_kerja=%E0%A4','#panel-bahan'])test('decline unsupported '+suffix,()=>{
 const address='/proses-aktif/pengeringan/LOT'+suffix;
 assert.equal(descriptor(address,origin),null);assert.equal(state(address,origin),null);
});
test('foreign origin and other phase are never candidates',()=>{
 for(const address of ['https://other.invalid/proses-aktif/pengeringan/LOT','//other.invalid/proses-aktif/pengeringan/LOT','/proses-aktif/sosoh/LOT','/pelanggan/proses-aktif/pengeringan/LOT','/proses-aktif/pengeringan/LOT/child']){
  assert.equal(descriptor(address,origin),null);assert.equal(state(address,origin),null);
 }
});
test('public data exact shape and bounds',()=>{
 assert.equal(validPackage(data),true);
 assert.equal(validPackage({...data,account_id:1}),false);
 assert.equal(validPackage({...data,variants:{...data.variants,pengeringan:{html:'x'.repeat(262145)}}}),false);
});
test('all private binding fields must match, stale session denied',()=>{
 assert.equal(validCatalog(envelope(),binding),true);
 for(const key of ['cap','konteks','sesi','sumber','sumber_sha256'])assert.equal(validCatalog({...envelope(),[key]:'old'},binding),false,key);
 assert.equal(validCatalog({...envelope(),permission:true},binding),false);
 assert.equal(validCatalog({...envelope(),entries:Array(51).fill(envelope().entries[0])},binding),false);
 assert.equal(validCatalog({...envelope(),entries:[{...envelope().entries[0],fase:'sosoh'}]},binding),false);
});
test('finished or redirected native page does not restore active tabs',()=>{
 assert.equal(restoreTab({querySelector:()=>null},'bahan','pengeringan'),null);
 const pending={classList:{contains:()=>true},hasAttribute:()=>true};
 assert.equal(restoreTab({querySelector:()=>pending},'bahan','pengeringan'),null);
});
