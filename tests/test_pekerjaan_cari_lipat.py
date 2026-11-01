"""Kartu informasi di details tertutup tetap dapat dicari dan dibuka."""
import shutil,subprocess
from pathlib import Path
import pytest

def test_informasi_terlipat_tidak_dihapus_oleh_saringan_dom():
 node=shutil.which('node')
 if not node:pytest.skip('Node tidak tersedia untuk menjalankan skrip halaman')
 source=Path('app/web/static/pekerjaan-cari.js').read_text()
 harness=r'''
const vm=require('vm'),assert=require('assert').strict;
const text={textContent:''},cap={textContent:''};
const card={hidden:false,dataset:{cari:'info uji',sup:'Pihak'},getClientRects:()=>[]};
const block={hidden:false,querySelectorAll:()=>[card],querySelector:()=>cap};
const input={value:'info',addEventListener:()=>{}},name={value:'',addEventListener:()=>{}};
const root={querySelector:s=>s.includes('name=cari')?input:s.includes('name=pemasok')?name:text};
const document={querySelector:()=>root,querySelectorAll:s=>s==='[data-blok]'?[block]:s==='[data-cari]'?[card]:[]};
vm.runInNewContext(SOURCE,{document,Array});
assert.equal(block.hidden,false);assert.equal(card.hidden,false);assert.equal(cap.textContent,1);assert.match(text.textContent,/1 kartu cocok/);
'''
 r=subprocess.run([node,'-e','const SOURCE='+__import__('json').dumps(source)+';'+harness],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
