/* Pure adopter contract only; not browser, native auth or pending recovery proof. */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url);
const adapter=require('../app/web/static/giling-native-html.js');
const origin='https://fixture.invalid';
const address='/proses-aktif/giling/GL-FIXTURE?tab_detail=hasil';
test('same exact native route/query, no API and no canonical rewrite',()=>{
 assert.equal(adapter.nativeAddress(address,origin),address);
 assert.equal(adapter.tabFromAddress(address,origin),'hasil');
 assert.equal(adapter.tabFromAddress('/proses-aktif/giling/GL-FIXTURE?tab_detail=other',origin),'ringkasan');
});
for(const value of ['/proses-aktif/sosoh/FIXTURE','//external.invalid/proses-aktif/giling/FIXTURE',
 '/proses-aktif/giling/FIXTURE?buka=hasil_giling','/proses-aktif/giling/FIXTURE?nilai=1',
 '/proses-aktif/giling/FIXTURE?tab_detail=hasil&tab_detail=qc','/proses-aktif/giling/FIXTURE#hasil',
 '/proses-aktif/giling/FIXTURE?company_id=1']){
 test('decline unsupported/action address '+value,()=>assert.equal(adapter.nativeAddress(value,origin),null));
}
test('post-install applies latest known native VIEW tab only',()=>{
 const clicks=[],queries=[];
 const content={querySelector(q){queries.push(q);return {disabled:false,click(){clicks.push(q);}};}};
 adapter.latestNativeTab(content,'qc');
 assert.deepEqual(clicks,['[data-giling-ringkas] button[role="tab"][data-sr-tab="qc"]']);
 assert.equal(adapter.latestNativeTab(content,'save'),null);
 assert.equal(queries.length,1);
});
test('disabled or unavailable native tab is never enabled by the adopter',()=>{
 assert.equal(adapter.latestNativeTab({querySelector:()=>({disabled:true,click(){throw Error('no');}})},'hasil'),null);
 assert.equal(adapter.latestNativeTab({querySelector:()=>null},'hasil'),null);
});
test('fresh native finished renderer is kept without forcing an active tab',()=>{
 let clicked=false;
 const content={querySelector(q){if(q==='[data-giling-ringkas]')return {pfGilingData:{aktif:false}};return {disabled:false,click(){clicked=true;}};}};
 assert.equal(adapter.restoreNativeTab(content,'hasil'),null);assert.equal(clicked,false);
});
test('active renderer missing its native VIEW tab fails closed',()=>{
 assert.throws(()=>adapter.restoreNativeTab({querySelector:q=>q==='[data-giling-ringkas]'?{pfGilingData:{aktif:true}}:null},'hasil'),/Tab proses/);
});
for(const state of [{uncertain:true},{busy:true},{action:'hasil'},{review:true}])test('native presentation guard wins over a requested view tab '+JSON.stringify(state),()=>{
 let clicked=false;
 const native={pfGilingData:{aktif:true},pfGilingPresentationState:state};
 assert.equal(adapter.restoreNativeTab({querySelector:q=>q==='[data-giling-ringkas]'?native:{disabled:false,click(){clicked=true;}}},'hasil'),null);
 assert.equal(clicked,false);
});
test('adopter declares afterInstall dependency and changes no mutation guard',()=>{
 const source=readFileSync(new URL('../app/web/static/giling-native-html.js',import.meta.url),'utf8');
 const code=source.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,'');
 assert.ok(source.includes('afterInstall({content})'));
 for(const forbidden of ['sessionStorage','localStorage','beforeunload','history.pushState','history.replaceState','fetch(','PadiKoreksiBahan'])assert.equal(code.includes(forbidden),false,forbidden);
});
