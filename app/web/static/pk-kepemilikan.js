(function(){
'use strict';
const root=document.querySelector('[data-pk-baru]');if(!root||root.dataset.ready)return;root.dataset.ready='1';
const form=root.querySelector('[data-pk-form]'),review=root.querySelector('[data-pk-review]'),status=root.querySelector('[data-pk-status]'),error=root.querySelector('[data-pk-error]'),recovery=root.querySelector('[data-pk-recovery]');
const fields=form.elements,save=root.querySelector('[data-pk-save]'),confirm=root.querySelector('[data-pk-confirm]');
const hint=new URLSearchParams(location.search);
const lockedSource=hint.has('sumber')||hint.has('kode');
const optionsPath=lockedSource?'detail-sumber?'+new URLSearchParams({sumber:hint.get('sumber')||'',kode:hint.get('kode')||'',pemilik_id:hint.get('pemilik_id')||'pabrik'}):'pilihan';
const storageKey='pk-kepemilikan:'+root.dataset.actor+':'+(document.getElementById('formulir-sesi')?.dataset.token||'')+':'+(hint.get('sumber')||hint.get('kode')||'baru')+':'+(hint.get('pemilik_id')||'');
let options=null,proof=null,snapshot=null,busy=false,uncertain=false,pending=false,leaving=false,key=crypto.randomUUID().replaceAll('-','');
const n=v=>Number(v).toLocaleString('id-ID',{maximumFractionDigits:3});
const el=(tag,text)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;};
function selected(){return options?.sumber.find(s=>token(s)===fields.sumber.value);}
function token(s){return s.sumber+'|'+(s.owner===null?'pabrik':s.owner);}
function current(){const s=selected();return {sumber:s?.sumber,warehouse_id:Number(fields.warehouse_id.value),dari:s?.owner??null,ke:fields.ke.value===''?null:Number(fields.ke.value),quantity:Number(fields.quantity.value),reason:fields.reason.value.trim()};}
function stash(){try{sessionStorage.setItem(storageKey,JSON.stringify({warehouse:fields.warehouse_id.value,source:fields.sumber.value,to:fields.ke.value,toQuery:targetInput.value,quantity:fields.quantity.value,reason:fields.reason.value,key,pending}));}catch(_){}}
function dirty(){return !!fields.reason.value||!!fields.quantity.value||pending;}
function setBusy(value){busy=value;if(value){++targetSequence;clearTimeout(targetTimer);closeTargets();}for(const e of form.querySelectorAll('input,textarea,select,button'))e.disabled=value||uncertain;save.disabled=value||uncertain||!confirm.checked;root.querySelector('[data-pk-edit]').disabled=value||uncertain;targetInput.disabled=value||uncertain||!selected();}
async function call(path,body){if(window.SESIFORM&&!SESIFORM.periksa())throw Error('Sesi/peran berubah. Buka kembali halaman dengan akun yang benar.');const c=new AbortController(),timer=setTimeout(()=>c.abort(),25000);try{const r=await fetch('/api/pk-kepemilikan/'+path,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',signal:c.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':document.getElementById('formulir-sesi')?.dataset.token||''},body:body?JSON.stringify(body):undefined});let d;try{d=await r.json();}catch(_){throw Error('Balasan server belum lengkap.');}if(!r.ok){const e=Error(typeof d.detail==='string'?d.detail:'Periksa isian dan izin pengalihan PK.');e.status=r.status;throw e;}return d;}finally{clearTimeout(timer);}}
function addOption(select,value,label){const o=el('option',label);o.value=value;select.append(o);}
function fillSources(preferred){fields.sumber.replaceChildren();for(const s of options.sumber.filter(s=>String(s.warehouse_id)===fields.warehouse_id.value))addOption(fields.sumber,token(s),s.label+' · '+s.pemilik+' · '+n(s.tersedia)+' kg bebas');if(preferred&&[...fields.sumber.options].some(o=>o.value===preferred))fields.sumber.value=preferred;fillTarget();}
function lockSourceFields(){if(!lockedSource)return;for(const f of [fields.warehouse_id,fields.sumber]){f.hidden=true;let info=f.parentElement.querySelector('[data-fixed-source]');if(!info){info=el('strong');info.dataset.fixedSource='1';f.parentElement.append(info);}info.textContent=f.selectedOptions[0]?.textContent||'Sumber tidak tersedia';}}
const target=root.querySelector('[data-pk-target]'),targetInput=root.querySelector('[data-pk-target-input]'),targetPanel=root.querySelector('[data-pk-target-panel]'),targetList=root.querySelector('[data-pk-target-list]'),targetStatus=root.querySelector('[data-pk-target-status]'),targetPages=root.querySelector('[data-pk-target-pages]');
let targetSelected=null,targetItems=[],targetIndex=-1,targetSequence=0,targetTimer=null,targetQuery='',targetMovingFocus=false;
function focusTargetInput(){targetMovingFocus=true;targetInput.focus({preventScroll:true});targetMovingFocus=false;}
function closeTargets(){targetPanel.hidden=true;targetInput.setAttribute('aria-expanded','false');targetInput.removeAttribute('aria-activedescendant');targetIndex=-1;}
function rememberTargets(items){for(const p of items){const i=options.pemilik.findIndex(x=>String(x.value)===String(p.value));if(i<0)options.pemilik.push(p);else options.pemilik[i]=p;}}
function setTarget(item){
 targetSelected=item||null;root.querySelector('#pk-pemilik-bantu').textContent='Pilih hasil pencarian untuk menetapkan pemilik tujuan.';fields.ke.replaceChildren();addOption(fields.ke,item?String(item.value):'__pilih__',item?.label||'Pilih pemilik tujuan');
 targetInput.value=item?.label||'';targetInput.setCustomValidity(item?'':'Pilih pemilik tujuan dari hasil pencarian.');closeTargets();
}
function chooseTarget(item){if(busy||uncertain||!selected())return;setTarget(item);proof=null;confirm.checked=false;stash();focusTargetInput();closeTargets();}
function renderTargets(items,meta={}){
 targetItems=items;targetIndex=-1;targetList.replaceChildren();targetPages.replaceChildren();targetInput.removeAttribute('aria-activedescendant');
 for(const [i,item] of items.entries()){
  const b=el('button',item.label);b.type='button';b.id='pk-target-'+i;b.setAttribute('role','option');b.setAttribute('aria-selected',String(!!targetSelected&&String(targetSelected.value)===String(item.value)));b.className='ko-target-option';b.onclick=()=>chooseTarget(item);targetList.append(b);
 }
 targetStatus.textContent=meta.message||((meta.total??items.length)+' pesanan sesuai pencarian'+(meta.pages>1?' · halaman '+meta.page+' dari '+meta.pages:'')+(!items.length?' · Tidak ada pilihan yang sesuai.':''));
 if(meta.retry){const b=el('button','Coba lagi');b.type='button';b.className='btn';b.onclick=()=>{focusTargetInput();findTargets(meta.page||1);};targetPages.append(b);}
 for(const [label,page] of [['Sebelumnya',(meta.page||1)-1],['Berikutnya',(meta.page||1)+1]])if(meta.pages>1&&page>=1&&page<=meta.pages){const b=el('button',label);b.type='button';b.className='btn';b.onclick=()=>{focusTargetInput();findTargets(page);};targetPages.append(b);}
}
function factoryTarget(query){return selected()?.owner!=null&&(!query.trim()||'pabrik'.includes(query.trim().toLowerCase()))?[{value:'',label:'Pabrik'}]:[];}
function fillTarget(preferred){
 ++targetSequence;clearTimeout(targetTimer);targetQuery='';const s=selected();setTarget(null);
 if(!s){root.querySelector('[data-pk-saldo]').textContent='Tidak ada stok PK bebas pada gudang ini.';targetInput.disabled=true;return;}
 const wanted=preferred===undefined?(s.owner===null?'__pilih__':''):String(preferred);
 const p=wanted===''&&s.owner!==null?{value:'',label:'Pabrik'}:options.pemilik.find(p=>String(p.value)===wanted&&String(p.value)!==String(s.owner));
 setTarget(p);fields.quantity.max=s.tersedia;targetInput.disabled=busy||uncertain;
 root.querySelector('[data-pk-saldo]').textContent=s.gudang+' · pemilik asal: '+s.pemilik+' · tersedia '+n(s.tersedia)+' kg. Lokasi tetap.';
}
async function restoreTarget(draft){
 fillTarget(draft.to);if(draft.to&&draft.to!=='__pilih__'&&!targetSelected&&selected()){
  const source=token(selected());const seq=++targetSequence;
  try{const d=await call('cari-tujuan?'+new URLSearchParams({pilihan_id:draft.to,...(selected().owner?{dari:selected().owner}:{})}));if(seq!==targetSequence||token(selected())!==source)return;rememberTargets(d.items);setTarget(d.items.find(p=>String(p.value)===String(draft.to)));if(!targetSelected)targetInput.setCustomValidity('Pemilik tujuan sebelumnya tidak tersedia. Pilih ulang.');}
  catch(_){targetInput.setCustomValidity('Pemilik tujuan belum dapat diperiksa. Cari dan pilih kembali.');root.querySelector('#pk-pemilik-bantu').textContent='Pemilik tujuan draf belum dapat dimuat. Isian lain tetap tersedia; cari dan pilih kembali.';}
 }
 if(!targetSelected&&draft.toQuery){targetInput.value=draft.toQuery;targetQuery=draft.toQuery;}
}
async function findTargets(page=1){
 if(busy||uncertain||!selected())return;clearTimeout(targetTimer);const seq=++targetSequence,source=token(selected()),q=targetQuery;
 targetPanel.hidden=false;targetInput.setAttribute('aria-expanded','true');renderTargets(factoryTarget(q),{message:'Mencari pemilik tujuan…'});
 try{
  const d=await call('cari-tujuan?'+new URLSearchParams({q,page,...(selected().owner?{dari:selected().owner}:{})}));
  if(seq!==targetSequence||!selected()||token(selected())!==source||busy||uncertain)return;
  rememberTargets(d.items);renderTargets([...factoryTarget(q),...d.items.filter(p=>String(p.value)!==String(selected().owner))],d);
 }catch(e){if(seq!==targetSequence||busy||uncertain)return;renderTargets(factoryTarget(q),{message:'Pencarian belum berhasil. Isian lain tetap tersedia.',retry:true,page});}
}
targetInput.addEventListener('focus',()=>{if(targetMovingFocus)return;targetQuery=targetSelected?'':targetInput.value;findTargets();});
targetInput.addEventListener('click',()=>{if(targetPanel.hidden){targetQuery=targetSelected?'':targetInput.value;findTargets();}});
targetInput.addEventListener('input',()=>{targetSelected=null;fields.ke.replaceChildren();addOption(fields.ke,'__pilih__','Pilih pemilik tujuan');targetInput.setCustomValidity('Pilih pemilik tujuan dari hasil pencarian.');targetQuery=targetInput.value;proof=null;confirm.checked=false;++targetSequence;clearTimeout(targetTimer);targetPanel.hidden=false;targetInput.setAttribute('aria-expanded','true');renderTargets(factoryTarget(targetQuery),{message:'Mencari pemilik tujuan…'});stash();targetTimer=setTimeout(()=>findTargets(),250);});
targetInput.addEventListener('keydown',e=>{
 if(e.key==='Escape'){if(!targetPanel.hidden){e.preventDefault();e.stopPropagation();closeTargets();}return;}
 if(e.key==='ArrowDown'||e.key==='ArrowUp'){
  e.preventDefault();if(targetPanel.hidden){targetQuery=targetSelected?'':targetInput.value;findTargets();return;}
  if(!targetItems.length)return;targetIndex=targetIndex<0?(e.key==='ArrowDown'?0:targetItems.length-1):(targetIndex+(e.key==='ArrowDown'?1:-1)+targetItems.length)%targetItems.length;
  for(const [i,b]of [...targetList.children].entries()){b.classList.toggle('ko-target-option--active',i===targetIndex);b.setAttribute('aria-selected',String(i===targetIndex));}
  const active=targetList.children[targetIndex];targetInput.setAttribute('aria-activedescendant',active.id);active.scrollIntoView({block:'nearest'});
 }else if(e.key==='Enter'&&!targetPanel.hidden){e.preventDefault();if(targetIndex>=0)chooseTarget(targetItems[targetIndex]);}
});
document.addEventListener('pointerdown',e=>{if(!target.contains(e.target))closeTargets();});
target.addEventListener('focusout',()=>setTimeout(()=>{if(!target.contains(document.activeElement))closeTargets();},0));
function resetReview(){proof=null;snapshot=null;confirm.checked=false;review.hidden=true;form.hidden=false;save.disabled=true;stash();}
function showPlan(plan){const container=root.querySelector('[data-pk-plan]');container.replaceChildren();container.append(el('p',plan.gudang+' · '+plan.sumber));const table=el('table');table.className='ko-table';const head=el('tr');for(const t of ['Pemilik','Sekarang','Sesudah'])head.append(el('th',t));table.append(head);const names=new Map(options.pemilik.map(p=>[String(p.value),p.label]));for(const id of new Set([...Object.keys(plan.balances_before),...Object.keys(plan.balances_after)])){const tr=el('tr');tr.append(el('th',id==='None'?'Pabrik':names.get(id)||'Pesanan #'+id),el('td',n(plan.balances_before[id]?.kg||0)+' kg'),el('td',n(plan.balances_after[id]?.kg||0)+' kg'));table.append(tr);}container.append(table,el('p','Total fisik: '+n(plan.physical_before)+' kg → '+n(plan.physical_after)+' kg. Gudang tetap sama.'));}
form.onsubmit=async e=>{e.preventDefault();if(busy||uncertain||!form.reportValidity()||!targetSelected)return;error.textContent='';snapshot=current();setBusy(true);try{proof=await call('periksa',{...snapshot,key});showPlan(proof.plan);form.hidden=true;review.hidden=false;confirm.checked=false;status.textContent='Periksa pemilik dan jumlah sebelum menyimpan.';root.querySelector('#pk-review-title').scrollIntoView({block:'nearest'});}catch(e){error.textContent=e.message;proof=null;snapshot=null;}finally{setBusy(false);if(!leaving)stash();}};
confirm.onchange=()=>save.disabled=busy||uncertain||!confirm.checked;
save.onclick=async()=>{if(busy||uncertain||!proof||!snapshot||!confirm.checked)return;pending=true;stash();setBusy(true);try{const result=await call('simpan',{...snapshot,key,baseline:proof.baseline,review:proof.review,confirm:true});pending=false;try{sessionStorage.removeItem(storageKey);}catch(_){}leaving=true;location.assign('/kepemilikan/'+result.id+'?kembali='+encodeURIComponent(root.dataset.kembali));}catch(e){uncertain=!e.status||e.status>=500;pending=uncertain;error.textContent=uncertain?'Hasil penyimpanan belum pasti. Periksa status terbaru sebelum mengirim lagi.':e.message;recovery.hidden=!(uncertain||e.status===409);confirm.checked=false;}finally{setBusy(false);if(!leaving)stash();}};
root.querySelector('[data-pk-edit]').onclick=()=>{if(!busy&&!uncertain){resetReview();status.textContent='Isian dipertahankan; stok belum berubah.';}};
form.addEventListener('input',()=>{proof=null;confirm.checked=false;stash();});
fields.warehouse_id.onchange=()=>{fillSources();resetReview();};fields.sumber.onchange=()=>{fillTarget();resetReview();};
root.querySelector('[data-pk-check]').onclick=async()=>{if(busy)return;setBusy(true);try{const result=await call('status/'+key);if(result.recorded){leaving=true;try{sessionStorage.removeItem(storageKey);}catch(_){}location.assign('/kepemilikan/'+result.id+'?kembali='+encodeURIComponent(root.dataset.kembali));return;}pending=false;uncertain=false;const targetDraft={to:fields.ke.value,toQuery:targetInput.value};options=await call(optionsPath);const old=fields.sumber.value;fillSources(old);await restoreTarget(targetDraft);lockSourceFields();resetReview();recovery.hidden=true;error.textContent='';status.textContent='Belum ditemukan catatan kiriman ini. Sumber terbaru sudah dibaca; periksa dampak lagi.';}catch(e){error.textContent='Status belum dapat dipastikan. '+e.message;}finally{setBusy(false);if(!leaving)stash();}};
const guide=root.querySelector('[data-pk-guide]');root.querySelector('[data-pk-panduan]').onclick=()=>guide.showModal();root.querySelector('[data-pk-tutup]').onclick=()=>guide.close();
window.addEventListener('beforeunload',e=>{if(root.isConnected&&!leaving&&(busy||dirty())){stash();e.preventDefault();e.returnValue='';}});
document.addEventListener('click',e=>{if(!root.isConnected||leaving||e.defaultPrevented||e.ctrlKey||e.metaKey||e.button!==0)return;const a=e.target.closest('a[href]');if(!a||a.target||!dirty())return;e.preventDefault();e.stopImmediatePropagation();const b=el('section');b.className='ko-box';b.append(el('h2','Isian belum disimpan'),el('p','Draf tersimpan pada perangkat ini dan belum mengubah stok.'));for(const [text,fn] of [['Tetap di halaman',()=>b.remove()],['Lanjut dengan draf tersimpan',()=>{stash();leaving=true;location.assign(a.href);}]]){const button=el('button',text);button.type='button';button.className='btn';button.onclick=fn;b.append(button);}root.prepend(b);},true);
(async()=>{try{options=await call(optionsPath);let draft;try{draft=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch(_){}for(const w of options.gudang)addOption(fields.warehouse_id,w.id,w.nama);if(!options.sumber.length){status.textContent='Tidak ada sumber PK bebas yang dapat dialihkan. Bahan di silo, bagian terpakai, dan sumber yang belum pasti tidak ditawarkan.';return;}const q=new URLSearchParams(location.search);const wid=draft?.warehouse||q.get('warehouse_id');if(wid&&[...fields.warehouse_id.options].some(o=>o.value===wid))fields.warehouse_id.value=wid;fillSources(draft?.source);if(!draft&&(q.get('sumber')||q.get('kode'))){const requestedOwner=q.get('pemilik_id')==='pabrik'?null:Number(q.get('pemilik_id'));const chosen=options.sumber.find(s=>(q.get('sumber')?s.sumber===q.get('sumber'):s.label===q.get('kode')&&s.sumber.startsWith('giling:'))&&(q.has('pemilik_id')?s.owner===requestedOwner:true));if(chosen){fields.warehouse_id.value=String(chosen.warehouse_id);fillSources(token(chosen));}else{fields.warehouse_id.value='';fillSources();error.textContent='Bagian PK dari tautan ini tidak lagi tersedia. Pilih gudang dan sumber terbaru.';}}if(draft){fields.quantity.value=draft.quantity||'';fields.reason.value=draft.reason||'';await restoreTarget(draft);key=draft.key||key;pending=!!draft.pending;uncertain=pending;recovery.hidden=!pending;}lockSourceFields();form.hidden=false;status.textContent=uncertain?'Status kiriman sebelumnya perlu diperiksa sebelum melanjutkan.':draft?'Draf dipulihkan. Periksa lagi dampak sebelum menyimpan.':'Pilih sumber dan pemilik tujuan. Membuka formulir tidak mengubah stok.';setBusy(false);}catch(e){error.textContent=e.message;status.textContent='Sumber PK belum dapat dibaca.';}})();
})();
