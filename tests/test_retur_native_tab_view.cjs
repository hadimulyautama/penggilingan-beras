const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {createHash}=require('node:crypto');
const {receiptTabPlan,nextReceiptAddress}=require('../app/web/static/retur-baca-native.js');
const {address}=require('../app/web/static/kerangka-retur-baca-ui-runtime.js');
const origin='https://fixture.invalid',identity={address:'/retur/7',cap:'fixture-cap',context:'fixture-context',token:'fixture-session'};
const tabs=['ringkasan','barang','tiket','riwayat'].map(t=>({href:origin+'/retur/7?tab_detail='+t+'#panel-'+t,controls:'panel-'+t}));
const plan=()=>receiptTabPlan(identity,tabs,origin,address);
function current(tab=1){const view=plan().views[tab];return {cap:identity.cap,context:identity.context,token:identity.token,frameAddress:identity.address,href:view.href,locationHref:view.full,selectedControls:view.controls,panelVisible:true,connected:true,sameRoot:true,sessionCurrent:true,nativeHandled:true};}
test('four exact native receipt hrefs create an immutable read-view plan',()=>{
 const p=plan();assert.ok(p);assert.equal(p.views.length,4);assert.ok(Object.isFrozen(p));assert.ok(Object.isFrozen(p.views));
 for(let i=0;i<4;i++)assert.equal(nextReceiptAddress(p,identity.address,current(i)),p.views[i].address);
});
test('successive local native tabs advance only from last validated frame address',()=>{
 const p=plan(),first=nextReceiptAddress(p,identity.address,current(1));
 const second={...current(2),frameAddress:first};
 assert.equal(nextReceiptAddress(p,first,second),p.views[2].address);
 assert.equal(nextReceiptAddress(p,identity.address,second),null);
});
for(const [field,value] of Object.entries({cap:'other-cap',context:'other-context',token:'other-session',frameAddress:'/retur/8',connected:false,sameRoot:false,sessionCurrent:false,nativeHandled:false,panelVisible:false,selectedControls:'panel-unknown',href:origin+'/retur/7?tab_detail=barang#not-panel',locationHref:origin+'/retur/8?tab_detail=barang#panel-barang'}))test('declines changed native view condition '+field,()=>assert.equal(nextReceiptAddress(plan(),identity.address,{...current(),[field]:value}),null));
for(const value of [origin+'/retur/8?tab_detail=barang#panel-barang',origin+'/retur/7?tab_detail=barang&buka=edit#panel-barang',origin+'/retur/7?tab_detail=barang&tab_detail=barang#panel-barang',origin+'/retur/7?tab_detail=unknown#panel-unknown',origin+'/retur/7?tab_detail=barang#panel-tiket','https://other.invalid/retur/7?tab_detail=barang#panel-barang'])test('unrecognized server href cannot become a plan '+value,()=>{
 const altered=tabs.map(t=>({...t}));altered[1].href=value;assert.equal(receiptTabPlan(identity,altered,origin,address),null);
});
test('new query or hash on current browser URL is not silently normalized',()=>{
 for(const locationHref of [origin+'/retur/7?tab_detail=barang&filter=other#panel-barang',origin+'/retur/7?tab_detail=barang#unknown',origin+'/retur/7?tab_detail=barang'])assert.equal(nextReceiptAddress(plan(),identity.address,{...current(),locationHref}),null);
});
test('only a readonly receipt and all four unique native views are accepted',()=>{
 assert.equal(receiptTabPlan({...identity,address:'/retur/tiket/7'},tabs,origin,address),null);
 assert.equal(receiptTabPlan({...identity,address:'/retur'},tabs,origin,address),null);
 assert.equal(receiptTabPlan(identity,tabs.slice(1),origin,address),null);
 assert.equal(receiptTabPlan(identity,[tabs[0],tabs[0],tabs[2],tabs[3]],origin,address),null);
 assert.equal(receiptTabPlan({...identity,extra:'untrusted'},tabs,origin,address),null);
});
test('native shared tab controller and URL owner remain byte-identical to1a9672a',()=>{
 const source=readFileSync(require.resolve('../app/web/static/detail_kirim_retur.js'));
 assert.equal(createHash('sha256').update(source).digest('hex'),'77b7306b8b2a3889f2109855f8cad57a4dd1a1e240f4e4c68222a09f20c4d750');
 const adapter=readFileSync(require.resolve('../app/web/static/retur-baca-native.js'),'utf8');
 assert.doesNotMatch(adapter,/history\.(?:replaceState|pushState)|fetch\(|sessionStorage|localStorage|method\s*:\s*['"]POST['"]/);
 assert.match(adapter,/afterInstall\(/);assert.match(adapter,/frame\.dataset\.pindahAlamat=next/);
});
