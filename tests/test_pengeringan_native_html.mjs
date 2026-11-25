import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {descriptor,restoreTab}=require('../app/web/static/pengeringan-native-html.js');
const {nativeTitle,validPackage,validCatalog,state,backContext}=require('../app/web/static/kerangka-pengeringan-ui-runtime.js');
const origin='https://fixture.invalid',source='a'.repeat(64),digest='b'.repeat(64);
const data={versi:1,sumber:source,variants:{pengeringan:{html:'',breadcrumb:'',title_parts:['Detail'],bar_control:''},pendinginan:{html:'',breadcrumb:'',title_parts:['Detail'],bar_control:''}}};
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
test('breadcrumb parent matches native Work family without foreign return URL',()=>{
 assert.deepEqual(backContext('/pekerjaan?tab=berjalan&gudang=g1',origin),{body:'/pekerjaan?tab=berjalan&gudang=g1',crumb:'/pekerjaan?tab=berjalan&gudang=g1'});
 assert.deepEqual(backContext('/kabar?sebelum=9',origin),{body:'/kabar?sebelum=9',crumb:'/pekerjaan?tab=berjalan'});
 assert.deepEqual(backContext('/pekerjaan',origin),{body:'/pekerjaan',crumb:'/pekerjaan?tab=berjalan'});
 for(const value of ['https://other.invalid/pekerjaan','//other.invalid/pekerjaan','/pengaturan','/berjalan'])assert.deepEqual(backContext(value,origin),{body:'/pekerjaan?tab=berjalan',crumb:'/pekerjaan?tab=berjalan'});
});

test('phase document titles differ exactly while code remains a text slot',()=>{
 assert.equal(nativeTitle(['Detail ','Pengeringan'],'LOT'),'Detail Pengeringan');
 assert.equal(nativeTitle(['Pendinginan aktif ',null],'LOT'),'Pendinginan aktif LOT');
 assert.equal(nativeTitle([null],null),null);
});
test('only existing action hrefs get full native editor navigation',()=>{
 const {nativeActions}=require('../app/web/static/pengeringan-native-html.js');
 const links=['?buka=kadar_air&nilai=LOT','?tab_detail=bahan','/riwayat-pengeringan/1/bobot','https://other.invalid/?buka=x'].map(href=>({mark:false,getAttribute:()=>href,setAttribute(k){if(k==='data-utuh')this.mark=true;}}));
 nativeActions({querySelectorAll:()=>links},origin);
 assert.deepEqual(links.map(x=>x.mark),[true,false,true,false]);
});
