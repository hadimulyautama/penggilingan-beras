import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {nativeAddress,configuration}=createRequire(import.meta.url)('../app/web/static/jasa-detail-native.js');
const ORIGIN='https://fixture.invalid';
test('explicit customer read family supports five native tabs and known read filters',()=>{
 for(const tab of ['ringkasan','penerimaan','proses','stok','pengambilan']){
  const address='/jasa/pelanggan/17?tab='+tab+'&status=&cari=&halaman=';
  assert.equal(nativeAddress(address,ORIGIN),address);
  assert.equal(configuration(address,ORIGIN).rootSelector,'[data-jasa-detail-kerangka]');
 }
});
test('cross-origin, action, focused alias and malformed deep links cannot mount',()=>{
 for(const address of ['//other.invalid/jasa/pelanggan/17','/jasa/17','/jasa/17/nota','/pelanggan/jasa/pelanggan/17','/jasa/pelanggan/0',
 '/jasa/pelanggan/017','/jasa/pelanggan/2147483648','/jasa/pelanggan/17?buka=tutup_jasa&nilai=1','/jasa/pelanggan/17?pesanan_id=1',
 '/jasa/pelanggan/17?tab=unknown','/jasa/pelanggan/17?tab=stok&tab=proses','/jasa/pelanggan/17?err=simpan','/jasa/pelanggan/17?company_id=2',
 '/jasa/pelanggan/17?pesanan_halaman=-1','/jasa/pelanggan/17?cari=%FF','/jasa/pelanggan/17?cari=%GG'])assert.equal(nativeAddress(address,ORIGIN),null,address);
});
test('retry restores read content without selecting a mutation control',()=>{
 let focused=false;const retry={},content={focus(){focused=true;}};
 configuration('/jasa/pelanggan/17',ORIGIN).restoreFocus({focus:retry,retry,content});
 assert.equal(focused,true);assert.equal(content.tabIndex,-1);
});
