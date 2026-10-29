"""Uji perilaku file share tanpa perangkat, akun, atau penerima eksternal."""
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.parametrize('scenario',['file','activation','cancel','denied','busy','unsupported','html','retry','duplicate'])
def test_bagikan_file_pdf_dengan_aktivasi_ketukan(scenario):
    node=shutil.which('node')
    if not node:pytest.skip('Node diperlukan untuk uji JavaScript berbagi PDF.')
    if int(subprocess.check_output([node,'--version'],text=True).strip().lstrip('v').split('.')[0])<18:
        pytest.skip('Uji File/Blob memerlukan Node 18 ke atas.')
    script=r"""
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const {File}=require('node:buffer');
(async()=>{
 const scenario=process.argv[1],source=fs.readFileSync(process.argv[2],'utf8');
 let active=false,fetches=0,shares=[],supported=scenario!=='unsupported',fail=scenario==='retry',html=scenario==='html',resolveShare;
 const button={dataset:{penerimaanShare:'/barang-masuk/1/laporan.pdf'},disabled:true,handlers:[],addEventListener(_,fn){this.handlers.push(fn)}};
 const status={textContent:''};
 const navigator={canShare:()=>supported,share(data){
   assert.equal(active,true,'share harus dipanggil langsung selama ketukan, sebelum await/fetch');
   shares.push(data);
   if(scenario==='cancel')return Promise.reject({name:'AbortError'});
   if(scenario==='denied')return Promise.reject({name:'NotAllowedError'});
   if(scenario==='busy')return new Promise(r=>resolveShare=r);
   return Promise.resolve();
 }};
 const context=vm.createContext({document:{querySelector:()=>button,getElementById:()=>status},location:{href:'https://uji/barang-masuk/1',origin:'https://uji'},URL,File,navigator,
   fetch:async(url,options)=>{fetches++;assert.equal(url,'https://uji/barang-masuk/1/laporan.pdf');assert.equal(options.credentials,'same-origin');assert.equal(options.cache,'no-store');
    if(fail)throw Error('Jaringan terputus');
    return {ok:true,redirected:html,headers:{get:key=>key==='content-type'?(html?'text/html':'application/pdf'):'attachment; filename="penerimaan.pdf"'},blob:async()=>new Blob(['%PDF-berkas-asli'],{type:'application/pdf'})};}
 });
 vm.runInContext(source,context);await new Promise(setImmediate);
 const tap=()=>{active=true;const result=button.handlers[0]();active=false;return result};
 if(scenario==='unsupported'){assert.equal(fetches,0);await tap();assert.equal(shares.length,0);assert.match(status.textContent,/Lihat PDF/);return;}
 if(scenario==='html'){await tap();assert.equal(shares.length,0);assert.match(status.textContent,/belum berhasil dimuat/);return;}
 if(scenario==='retry'){
   assert.match(status.textContent,/belum berhasil dimuat/);fail=false;await tap();assert.equal(shares.length,0,'tidak boleh otomatis share setelah retry fetch');
 }
 assert.equal(button.disabled,false);
 if(scenario==='duplicate'){vm.runInContext(source,context);assert.equal(button.handlers.length,1);}
 if(scenario==='busy'){
   let done=tap();assert.equal(button.disabled,true);await tap();assert.equal(shares.length,1);resolveShare();await done;
 }else await tap();
 assert.equal(shares.length,1);assert.equal(shares[0].url,undefined,'yang dibagikan berkas, bukan URL berizin');
 assert.equal(shares[0].files[0].type,'application/pdf');assert.equal(shares[0].files[0].name,'penerimaan.pdf');
 assert.equal(await shares[0].files[0].text(),'%PDF-berkas-asli');assert.equal(button.disabled,false);
 if(scenario==='cancel')assert.match(status.textContent,/dibatalkan/);
 if(scenario==='denied')assert.match(status.textContent,/belum berhasil dibagikan/);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result=subprocess.run([node,'-e',script,scenario,str(Path('app/web/static/pdf-penerimaan.js').resolve())],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
