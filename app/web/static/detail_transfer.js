/* Penyajian saja: POST, nilai dasar, izin, saldo dan penjaga hilir tetap
   memakai formulir serta layanan transfer lama. */
(function(){
 'use strict';
 function pasang(root,navLama){
  if(!root||root.dataset.rhtReady)return;root.dataset.rhtReady='1';
  const tabs=[...root.querySelectorAll('.transfer-tabs [role=tab]')],menu=root.querySelector('.rhs-menu');
  // Pada 422 koreksi.js mengganti main tanpa menjalankan ulang script.
  // Pakai isian dan baseline dari jawaban server, bukan baseline tersimpan.
  const parent=root.parentElement;
  if(parent&&!parent._transferDesainObserver){parent._transferDesainObserver=new MutationObserver(records=>{for(const r of records)for(const added of r.addedNodes)if(added.nodeType===1&&added.matches('[data-riwayat-transfer]'))pasang(added);});parent._transferDesainObserver.observe(parent,{childList:true});}
  const guide=root.querySelector('#rht-panduan');
  for(const b of root.querySelectorAll('[data-rht-guide]'))b.onclick=()=>{if(menu)menu.open=false;guide.showModal();};root.querySelector('[data-rht-guide-close]').onclick=()=>guide.close();
  const box=root.querySelector('#koreksi-transfer .riwayat-koreksi'),form=box&&box.querySelector('form');let editor;
  const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  if(form){
   editor=document.createElement('dialog');editor.className='rht-correction';editor.setAttribute('aria-labelledby','rht-correction-title');
   const head=document.createElement('header');head.className='rht-correction-head';const title=node('h2','Koreksi berat transfer');title.id='rht-correction-title';
   const close=node('button','×');close.type='button';close.className='btn';close.setAttribute('aria-label','Tutup koreksi');close.onclick=()=>editor.close();head.append(title,close);editor.append(head);box.before(editor);editor.append(box);box.open=true;
   const trigger=node('button','Buka koreksi berat transfer');trigger.type='button';trigger.className='btn';trigger.dataset.rhtOpenEditor='';editor.before(trigger);trigger.onclick=()=>bukaEditor();
  }
  function bukaEditor(){if(editor&&!editor.open){if(menu)menu.open=false;editor.showModal();}}
  function tampil(id){
   tabs.forEach(t=>{const active=t.getAttribute('aria-controls')===id;t.setAttribute('aria-selected',String(active));root.querySelector('#'+t.getAttribute('aria-controls')).hidden=!active;});
   for(const a of root.querySelectorAll('.rht-actions a[href*="buka="]')){const u=new URL(a.href);u.searchParams.set('tab_detail',id.slice(6));u.hash=id;a.href=u.href;}
  }
  function dariHash(){
   let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(_){return;}
   if(!id&&new URL(location.href).searchParams.get('buka_koreksi')==='1')id='koreksi-transfer';
   const map={'ringkasan-proses':'panel-ringkasan','tindakan-proses':'tindakan-proses','bahan-proses':'panel-bahan','permintaan':'panel-permintaan','riwayat-proses':'panel-riwayat','catatan-hasil':'koreksi-transfer'};
   if(!id)return;const target=root.querySelector('#'+CSS.escape(map[id]||id));if(!target)return;const panel=target.closest('[role=tabpanel]');if(!panel)return;tampil(panel.id);
   if(target.id==='koreksi-transfer')bukaEditor();for(let el=target.parentElement;el&&el!==root;el=el.parentElement)if(el.tagName==='DETAILS')el.open=true;
   if(!editor||!editor.open)target.scrollIntoView({block:'nearest'});
  }
  root.addEventListener('click',e=>{
   const a=e.target.closest('a');if(!a||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||a.target||a.hasAttribute('download'))return;
   const u=new URL(a.href),now=new URL(location.href),base=new URL(tabs[0].href),tab=u.searchParams.get('tab_detail');
   if(u.origin!==now.origin||u.pathname!==base.pathname||u.searchParams.has('buka')||u.searchParams.get('halaman_transfer')!==now.searchParams.get('halaman_transfer')||!tabs.some(t=>t.getAttribute('aria-controls')==='panel-'+tab))return;
   e.preventDefault();e.stopPropagation();if(editor&&editor.open)editor.close();tampil('panel-'+tab);history.replaceState(history.state,'',u.pathname+u.search+u.hash);dariHash();
  });
  root.querySelector('.transfer-tabs').addEventListener('keydown',e=>{let i=tabs.indexOf(e.target);if(i<0||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();i=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[i].focus();tabs[i].click();});
  if(window.PINDAH)PINDAH.pasang(window,'hashchange',dariHash);else window.addEventListener('hashchange',dariHash);
  tampil(tabs.find(t=>t.getAttribute('aria-selected')==='true').getAttribute('aria-controls'));dariHash();if(form&&form.querySelector('[name=wajib_periksa]'))bukaEditor();if(!form)return;
  const save=form.querySelector('button[type=submit]'),review=document.createElement('section');review.className='rhs-review rht-review';review.hidden=true;review.dataset.rhtReview='';form.append(review);save.textContent='Periksa koreksi';let checked=false;
  const reset=()=>{checked=false;review.hidden=true;save.hidden=false;};form.addEventListener('input',reset);form.addEventListener('change',reset);
  const kg=n=>new Intl.NumberFormat('id-ID',{maximumFractionDigits:2}).format(Number(n))+' kg';
  new MutationObserver(()=>{const b=review.querySelector('[data-rht-confirm]');if(b){b.disabled=!!form.dataset.menyimpan;b.textContent=b.disabled?'Menyimpan…':'Konfirmasi & simpan koreksi';}}).observe(form,{attributes:true,attributeFilter:['data-menyimpan']});
  form.addEventListener('submit',e=>{
   if(e.submitter&&e.submitter.hasAttribute('data-rht-confirm')&&checked)return;
   e.preventDefault();e.stopPropagation();if(!form.reportValidity())return;
   const weight=form.elements.namedItem('hasil_transfer').value,before=form.elements.namedItem('dasar_transfer').value,code=root.querySelector('.rhs-code').textContent.trim();
   review.replaceChildren(node('h3','Periksa dampak koreksi'));const facts=document.createElement('dl');facts.className='transfer-fakta';
   for(const [label,value] of [['Catatan lama',code+' · '+kg(before)+' · akan dibatalkan'],['Transfer pengganti',Number(weight)>0?'Catatan baru · '+kg(weight):'Tidak dibuat · berat akhir 0 kg'],['Tujuan',root.querySelector('[data-rht-tujuan]').textContent.trim()+' · tetap'],['Alasan',form.elements.namedItem('alasan').value]]){const row=document.createElement('div');row.append(node('dt',label),node('dd',value));facts.append(row);}
   review.append(facts,node('p','Catatan lama beserta bobot dan packing-nya tetap tersimpan. Nilai terbaru, hak akses, saldo dan pemakaian terkait tetap diperiksa server saat disimpan.'));
   const back=node('button','Ubah isian');back.type='button';back.className='btn';back.onclick=reset;const confirm=node('button','Konfirmasi & simpan koreksi');confirm.type='submit';confirm.className='btn btn--utama';confirm.dataset.rhtConfirm='';const actions=document.createElement('div');actions.className='rhs-actions';actions.append(back,confirm);review.append(actions);checked=true;save.hidden=true;review.hidden=false;review.scrollIntoView({block:'nearest'});
  });
 }
 pasang(document.querySelector('[data-riwayat-transfer]'));
})();
