/* Penyajian riwayat selesai. Node koreksi/QC tetap dipakai selama berganti tab.
   Pemeriksaan dan penyimpanan asli tidak dipindahkan ke script ini. */
window.PadiRiwayatSosohDesain=function(root){
 'use strict';
 root=root||document.querySelector('[data-riwayat-sosoh]');if(!root||root.dataset.rhsReady)return;root.dataset.rhsReady='1';
 // Penolakan koreksi mengganti main saja melalui koreksi.js. Aktifkan lagi
 // kontrol dan QC pada jawaban server tanpa mengubah formulir atau aturannya.
 const parent=root.parentElement;
 if(parent&&!parent._rhsWatch){
  parent._rhsWatch=new MutationObserver(records=>{for(const record of records)for(const added of record.addedNodes){if(added.nodeType!==1||!added.matches('[data-riwayat-sosoh]'))continue;
   window.PadiRiwayatSosohDesain(added);
   const qc=added.querySelector('[data-qc-sosoh]');
   if(qc?.querySelector('[data-qc-editor]')&&!qc.dataset.siap){const original=added.querySelector('#rhs-panel-qc script[src*="qc-sosoh.js"]');if(original){const script=document.createElement('script');script.src=original.src;added.append(script);}}
  }});parent._rhsWatch.observe(parent,{childList:true});
 }
 const key=root.dataset.rhsActor+'|'+(root.querySelector('.riwayat-koreksi__form [name=_csrf]')?.value||'');
 const memory=window.PADI_RIWAYAT_SOSOH_DRAF||(window.PADI_RIWAYAT_SOSOH_DRAF={}),cache=memory[key]||(memory[key]={});
 const tabs=[...root.querySelectorAll('[data-rhs-tab]')],panels=[...root.querySelectorAll('[data-rhs-panel]')],guide=root.querySelector('#rhs-panduan');
 function show(id,focus=false){if(!panels.some(p=>p.dataset.rhsPanel===id))return;root.dataset.rhsSelected=id;cache.tab=id;for(const p of panels)p.hidden=p.dataset.rhsPanel!==id;for(const b of tabs)b.setAttribute('aria-selected',String(b.dataset.rhsTab===id));if(focus)root.querySelector('[data-rhs-panel="'+id+'"]').scrollIntoView({block:'nearest'});}
 for(const b of tabs)b.onclick=e=>{if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0)return;e.preventDefault();show(b.dataset.rhsTab);};
 for(const b of root.querySelectorAll('[data-rhs-go]'))b.onclick=e=>{e.preventDefault();show(b.dataset.rhsGo,true);};
 root.querySelector('.rhs-tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const i=tabs.indexOf(document.activeElement),n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;e.preventDefault();show(tabs[n].dataset.rhsTab);tabs[n].focus();});
 for(const b of root.querySelectorAll('[data-rhs-edit]'))b.onclick=()=>{const menu=b.closest('.rhs-menu');if(menu)if(menu)menu.open=false;show('hasil',true);const box=root.querySelector('.riwayat-koreksi');if(box){box.open=true;box.querySelector('input[type=number]')?.focus();}else root.querySelector('[data-rhs-correction]')?.scrollIntoView({block:'nearest'});};
 for(const b of root.querySelectorAll('[data-rhs-guide]'))b.onclick=()=>{const menu=b.closest('.rhs-menu');if(menu)if(menu)menu.open=false;guide.showModal();};
 root.querySelector('[data-rhs-guide-close]').onclick=()=>guide.close();
 guide.addEventListener('click',e=>{if(e.target===guide){const r=guide.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)guide.close();}});
 root.querySelectorAll('[data-rhs-print]').forEach(b=>b.onclick=()=>window.print());
 function hash(){let id;try{id=decodeURIComponent(location.hash.slice(1))}catch(_){return}const target=document.getElementById(id);if(!target||!root.contains(target))return;const p=target.closest('[data-rhs-panel]');if(p){show(p.dataset.rhsPanel);for(let n=target.parentElement;n&&n!==root;n=n.parentElement)if(n.tagName==='DETAILS')n.open=true;target.scrollIntoView({block:'nearest'});}}
 show(root.dataset.rhsReturn==='1'?root.dataset.tabAwal:(cache.tab||root.dataset.tabAwal));if(root.dataset.rhsReturn!=='1')hash();if(window.PINDAH)PINDAH.pasang(window,'hashchange',hash);else window.addEventListener('hashchange',hash);
 // Hanya pratinjau lokal. POST tetap mengirim seluruh field dan token asli.
 let form=root.querySelector('.riwayat-koreksi__form');if(!form)return;
 // QC menyegarkan seluruh bingkai. Pindahkan node draf yang sama, termasuk
 // dasar_* lama; mengganti dasar dengan angka baru akan melewati deteksi
 // perubahan bersamaan. Kunci terikat akun, view, proses dan sesi formulir.
 if(cache.form&&root.dataset.rhsReturn!=='1'){form.replaceWith(cache.form);form=cache.form;const box=form.closest('details');if(box)box.open=true;}
 if(form.dataset.rhsFormReady)return;form.dataset.rhsFormReady='1';
 form.addEventListener('input',()=>{cache.form=form});form.addEventListener('change',()=>{cache.form=form});
 const save=form.querySelector('button[type=submit]'),review=document.createElement('section');review.className='rhs-review';review.hidden=true;review.dataset.rhsReview='';form.append(review);save.textContent='Periksa koreksi';
 const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
 let checked=false;
 new MutationObserver(()=>{const b=form.querySelector('[data-rhs-confirm]');if(b){b.disabled=!!form.dataset.menyimpan;b.textContent=form.dataset.menyimpan?'Menyimpan…':'Konfirmasi & simpan koreksi';}}).observe(form,{attributes:true,attributeFilter:['data-menyimpan']});
 const reset=()=>{checked=false;review.hidden=true;save.hidden=false;};form.addEventListener('input',reset);form.addEventListener('change',reset);
 form.addEventListener('submit',e=>{if(e.submitter?.hasAttribute('data-rhs-confirm')&&checked){delete cache.form;return;}e.preventDefault();e.stopPropagation();if(!form.reportValidity())return;review.replaceChildren(node('h3','Periksa perubahan hasil'));
  for(const field of form.querySelectorAll('input[name^="hasil_"]')){const name=field.name.slice(6),before=form.elements.namedItem('dasar_'+name),row=document.createElement('div');row.className='rhs-pair';row.append(node('span',field.closest('label').querySelector('span').textContent),node('strong',(before?.value??'Belum tersedia')+' → '+field.value+' kg'));review.append(row);}
  review.append(node('p','Alasan: '+form.elements.namedItem('alasan').value),node('p','Nilai terbaru, hak akses dan pemakaian terkait tetap diperiksa layanan ketika disimpan.'));
  const back=node('button','Ubah isian');back.type='button';back.className='btn';back.onclick=reset;const confirm=node('button','Konfirmasi & simpan koreksi');confirm.type='submit';confirm.className='btn btn--utama';confirm.dataset.rhsConfirm='';const actions=document.createElement('div');actions.className='rhs-actions';actions.append(back,confirm);review.append(actions);checked=true;review.hidden=false;save.hidden=true;review.scrollIntoView({block:'nearest'});
 });
};
window.PadiRiwayatSosohDesain();
