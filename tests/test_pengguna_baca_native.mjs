import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url),{state,validData,validPermission,validCatalog,stripNative}=require('../app/web/static/kerangka-pengguna-ui-runtime.js');
const {configuration,emptyPeopleCase,updateBreadcrumb}=require('../app/web/static/pengguna-baca-native.js');
const origin='https://fixture.invalid',source='a'.repeat(64),ctx='context',cap='cap',token='session';
const variants=['staf','staf-super','staf-detail','pelanggan','pelanggan-detail'];

test('fresh native breadcrumb preserves only its unique focused equivalent',()=>{
 function run({outside=false,href='/pengaturan',duplicates=1,focusDuringReplace=false,unsafe=false}={}){
  const body={},other={},document={body,activeElement:null,importNode:n=>n};let focused=0,replaced=0;
  const old={getAttribute:()=>'/pengaturan',matches:s=>s==='a[href]'||s==='.desktop-back'};
  const next={getAttribute:()=>href,matches:s=>s==='.desktop-back',focus:options=>{assert.deepEqual(options,{preventScroll:true});focused++;document.activeElement=next;}};
  document.activeElement=outside?other:old;
  const source={querySelector:()=>unsafe?{}:null,childNodes:[next]};
  const target={contains:n=>n===old,replaceChildren:()=>{replaced++;if(!outside)document.activeElement=focusDuringReplace?other:body;},querySelectorAll:()=>Array(duplicates).fill(next)};
  updateBreadcrumb(source,target,document);
  return {focused,replaced};
 }
 assert.deepEqual(run(),{focused:1,replaced:1});
 for(const options of [{outside:true},{href:'/pengguna'},{duplicates:2},{focusDuringReplace:true}])assert.deepEqual(run(options),{focused:0,replaced:1});
 assert.deepEqual(run({unsafe:true}),{focused:0,replaced:0});
});
const data={versi:1,sumber:source,variants:Object.fromEntries(variants.map(v=>[v,{title:v,html:'',breadcrumb:'',bar:'',kembali:'/pengaturan'}])),styles:{},scripts:{}};
function permission(){return {versi:1,sumber:source,cap,konteks:ctx,sesi:token,targets:{'/pengguna':'staf-super','/pengguna/pelanggan':'pelanggan'}};}
function catalog(){return {versi:1,sumber:source,source_address:'/pengguna',source_sha256:'b'.repeat(64),cap,konteks:ctx,sesi:token,entries:[{alamat:'/pengguna/12',variant:'staf-detail',title:'Nama fixture'}]};}
for(const path of ['/pengguna','/pengguna/12','/pengguna/pelanggan','/pengguna/pelanggan/12','/pengguna/pelanggan?cari_akun=Budi&halaman_akun=2'])test('exact native read '+path,()=>assert.ok(state(path,origin)));
for(const path of ['/pengguna/buat','/pengguna/reset','/pengguna/0','/pengguna/2147483648','/pengguna/1?err=nama','/pengguna/pelanggan/kontak','/pengguna/pelanggan/buat','/pengguna/pelanggan/1/status','/pengguna/pelanggan?ok=diubah','/pengguna/pelanggan?company_id=2','/pengguna/pelanggan?cari_akun=a&cari_akun=b','/pengguna/pelanggan?cari_akun=%FF','/pengguna/pelanggan?halaman_akun=abc','/pelanggan/pengguna','//other.invalid/pengguna'])test('default decline '+path,()=>{assert.equal(state(path,origin),null);assert.equal(configuration(path,origin),null);});
test('native Python strip semantics and Unicode codepoint bound for query echo',()=>{
 assert.equal(stripNative('\x1c\x85\u3000Budi\u3000'),'Budi');
 assert.equal(stripNative('\uFEFFBudi'),'\uFEFFBudi');
 const p=state('/pengguna/pelanggan?cari_akun='+encodeURIComponent('🙂'.repeat(101)),origin);
 assert.equal(Array.from(p.search).length,100);
});
test('public data contains only exact bounded structural components',()=>{
 assert.equal(validData(data),true);
 assert.equal(validData({...data,account_id:12}),false);
 assert.equal(validData({...data,variants:{...data.variants,'staf-detail':{...data.variants['staf-detail'],html:'x'.repeat(65537)}}}),false);
});
test('native doors bind each exact actor context, CAP and session',()=>{
 assert.equal(validPermission(permission(),data,ctx,cap,token),true);
 for(const field of ['cap','konteks','sesi','sumber'])assert.equal(validPermission({...permission(),[field]:'old'},data,ctx,cap,token),false);
 assert.equal(validPermission({...permission(),targets:{'/pengguna':'staf','/pengguna/pelanggan':'pelanggan'}},data,ctx,cap,token),false);
 assert.equal(validPermission({...permission(),targets:{'/pengguna':'staf'}},data,ctx,cap,token),true);
 assert.equal(validPermission({...permission(),targets:{'/pengguna/12':'staf-detail'}},data,ctx,cap,token),false);
});
test('actual row catalogue cannot switch source family, role flags or records',()=>{
 assert.equal(validCatalog(catalog(),data,ctx,cap,token,'/pengguna'),true);
 assert.equal(validCatalog(catalog(),data,ctx,cap,'old','/pengguna'),false);
 assert.equal(validCatalog(catalog(),data,ctx,cap,token,'/pengguna/pelanggan'),false);
 assert.equal(validCatalog({...catalog(),entries:[{alamat:'/pengguna/pelanggan/12',variant:'pelanggan-detail',title:'Title'}]},data,ctx,cap,token,'/pengguna'),false);
 assert.equal(validCatalog({...catalog(),entries:[...catalog().entries,...catalog().entries]},data,ctx,cap,token,'/pengguna'),false);
 assert.equal(validCatalog({...catalog(),source_address:'/pengguna?ok=1'},data,ctx,cap,token,'/pengguna?ok=1'),false);
 assert.equal(validCatalog({...catalog(),entries:Array.from({length:201},(_,i)=>({alamat:'/pengguna/'+(i+1),variant:'staf-detail',title:'Name'}))},data,ctx,cap,token,'/pengguna'),false);
});
test('readonly mounting config adds no writer or transaction API target',()=>{
 for(const path of ['/pengguna','/pengguna/12','/pengguna/pelanggan/12']){
  const c=configuration(path,origin);assert.equal(c.address,path);assert.equal(c.contentAttribute,'data-pengguna-baca-native-isi');
 }
 assert.equal(configuration('/api/actions/save',origin),null);
 assert.equal(configuration('/pengguna/reset',origin),null);
});

test('only native true-empty staff account-choice keeps disabled inert fields',()=>{
 assert.equal(emptyPeopleCase('staf-super','Buatkan akun','Semua orang yang aktif sudah punya akun.',false),true);
 assert.equal(emptyPeopleCase('staf','Buatkan akun','Semua orang yang aktif sudah punya akun.',false),true);
 for(const values of [
  ['pelanggan','Buatkan akun','Semua orang yang aktif sudah punya akun.',false],
  ['staf','Buatkan akun','Memuat data',false],
  ['staf','Buatkan akun','Semua orang yang aktif sudah punya akun.',true],
  ['staf','Akun yang ada','Semua orang yang aktif sudah punya akun.',false],
 ])assert.equal(emptyPeopleCase(...values),false);
});

test('actual five-variant public package keeps valid factory input and named pending sections',()=>{
 const file=readFileSync(new URL('../app/web/static/kerangka-pengguna-ui.js',import.meta.url),'utf8');
 const actual=JSON.parse(file.split('window.PadiKerangkaPenggunaData=',2)[1].split(';\n',1)[0]);
 assert.equal(validData(actual),true);
 for(const variant of variants){
  const component=actual.variants[variant];
  const section=component.html.match(/<section\b[^>]*\bdata-pengguna-baca-native\b[^>]*>/);
  assert.ok(section,variant);
  assert.match(section[0],/\baria-label="[^"]+"/,variant);
  const permissionFixture={...permission(),sumber:actual.sumber};
  assert.equal(validPermission(permissionFixture,actual,ctx,cap,token),true,variant);
 }
 const runtime=readFileSync(new URL('../app/web/static/kerangka-pengguna-ui-runtime.js',import.meta.url),'utf8');
 assert.ok(runtime.includes("root.setAttribute('aria-label',title)"),'Factory must fill a verified staff-detail name, not leave its compiled placeholder');
 const unchangedSdk=readFileSync(new URL('../hmu_tampilan/static/pindah.js',import.meta.url),'utf8');
 assert.ok(unchangedSdk.includes('!isi.querySelector("h1,section[aria-label],[role=region][aria-label]")'));
});
