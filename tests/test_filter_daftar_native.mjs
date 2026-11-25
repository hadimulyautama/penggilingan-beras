import {test} from 'node:test';import assert from 'node:assert/strict';import {createRequire}from'node:module';
const require=createRequire(import.meta.url);const {address,nativeLink,choose}=require('../app/web/static/filter-daftar-native.js');
const origin='https://uji';
test('query encoding/order stays exact for correlation while native links reset only native paging',()=>{
 const value='/pekerjaan?halaman=3&cari=Bu+Uji%7E&pemasok=ABC&tab=berjalan&asal=keputusan&kategori=packing',s=address(value,origin);
 assert.equal(s.address,value);assert.equal(s.selection,'berjalan');
 assert.equal(nativeLink(s,{tab:'tindakan',asal:'',kategori:'',grup:'',informasi:''}),'/pekerjaan?cari=Bu+Uji~&pemasok=ABC&tab=tindakan');
});
for(const value of ['https://uji/pekerjaan','//uji/pekerjaan','/pekerjaan#tab','/pekerjaan/1','/pelanggan/pekerjaan','/barang-masuk?status=','/pekerjaan?buka=','/pekerjaan?nilai=','/pekerjaan?informasi=2','/barang-masuk?status=diterima&status=belum','/pekerjaan?pelanggan_id=0','/pekerjaan?halaman=2147483648','/pekerjaan?halaman=١','/pekerjaan?gudang=wh:1','/pekerjaan?company_id=2','/pekerjaan?cari=%FF','/pekerjaan?cari=%XX','/aksi?grup=bahan','/berjalan','/keputusan','/mutu'])test('decline native-only input '+value,()=>assert.equal(address(value,origin),null));
function option(value,disabled=false){return {value,disabled,selected:false,attrs:{},toggleAttribute(k,v){if(v)this.attrs[k]='';else delete this.attrs[k];}};}
test('an already present native option can be selected; a disabled or absent option cannot be minted',()=>{
 const options=[option(''),option('g1'),option('g2',true)],select={options,value:''};
 assert.equal(choose(select,'g1'),true);assert.equal(select.value,'g1');assert.equal(options[1].selected,true);assert.deepEqual(options[1].attrs,{selected:''});
 assert.equal(choose(select,'g2'),false);assert.equal(choose(select,'other-company'),false);assert.equal(select.value,'g1');assert.equal(options.length,3);
 assert.equal(choose(null,'g1'),false);
});
test('finite raw filters do not make customer references into permissions or labels',()=>{
 const s=address('/barang-masuk?status=diterima&pelanggan_id=42&pemasok=Nama+synthetic&halaman=8',origin);
 assert.equal(s.selection,'diterima');assert.equal(s.u.searchParams.get('pelanggan_id'),'42');assert.equal('allowed'in s,false);assert.equal('customerName'in s,false);
 assert.equal(nativeLink(s,{status:'belum'}),'/barang-masuk?status=belum&pelanggan_id=42&pemasok=Nama+synthetic');
});
