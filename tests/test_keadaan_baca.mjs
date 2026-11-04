import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const code=fs.readFileSync(new URL('../hmu_tampilan/static/keadaan-baca.js',import.meta.url),'utf8');
function fixture(){
 const calls=[],fields=[{id:'bm-cari',name:'cari',tagName:'INPUT',type:'search',value:'',checked:false},{name:'pemasok',tagName:'SELECT',type:'select-one',value:'',checked:false}];
 fields.forEach(e=>e.dispatchEvent=event=>{calls.push(event.type);assert.deepEqual(fields.map(x=>x.value),['belum dicari','Contoh A']);hint.hidden=false;});
 const hint={hidden:true},detail={id:'filter',open:false,closest(){return null;}};
 const root={parentElement:null,scrollHeight:1000,clientHeight:400,isConnected:true,scrollLeft:0,tagName:'MAIN',id:'isi-halaman',matches:()=>true,contains:()=>false,getBoundingClientRect:()=>({top:0,bottom:400}),querySelectorAll(selector){if(selector==='details')return [detail];if(selector.startsWith('input:')){assert.ok(selector.includes(':not([type=hidden])'));assert.ok(selector.includes(':not([type=password])'));assert.ok(selector.includes(':not([type=file])'));return fields;}return [];}};
 Object.defineProperty(root,'scrollTop',{get:()=>200,set:v=>{assert.equal(hint.hidden,false,'Turunan formulir harus pulih sebelum gulir');calls.push('scroll');}});
 const context={window:{},document:{getElementById:()=>null,scrollingElement:root,activeElement:null},CSS:{escape:x=>x},innerHeight:400,getComputedStyle:()=>({overflowY:'auto'}),CustomEvent:class{constructor(type,o){this.type=type;this.bubbles=o.bubbles;assert.equal(o.bubbles,true);}}};vm.runInNewContext(code,context);
 return {api:context.window.KEADAAN_BACA,root,fields,hint,detail,calls};
}
test('Pemulihan memberitahu UI setelah seluruh nilai pulih, sebelum gulir; tanpa input/change',()=>{
 const f=fixture();const s=f.api.ambil(f.root);s.fields[0].value='belum dicari';s.fields[1].value='Contoh A';s.details.set(':filter',true);f.api.pulihkan(f.root,s);
 assert.equal(f.fields[0].value,'belum dicari');assert.equal(f.detail.open,true);assert.equal(f.hint.hidden,false);assert.deepEqual(f.calls,['pf:read-state-restored','pf:read-state-restored','scroll']);
});
test('Tanpa snapshot tidak mengirim peristiwa atau mengubah formulir',()=>{const f=fixture();f.api.pulihkan(f.root,null);assert.deepEqual(f.calls,[]);assert.equal(f.fields[0].value,'');});
