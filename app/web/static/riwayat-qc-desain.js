/* Presentasi riwayat QC. Tidak menghitung ulang mutu, mengirim transaksi,
   atau mengganti editor asli: perpindahan tab mempertahankan node dan draf. */
(function(){
 'use strict';
 const root=document.querySelector('[data-riwayat-qc]');
 if(!root||root.dataset.rqdReady)return;root.dataset.rqdReady='1';
 const menu=root.querySelector('.rhs-menu'),guide=root.querySelector('#rqd-panduan');
 for(const b of root.querySelectorAll('[data-rqd-guide]'))b.onclick=()=>{if(menu)menu.open=false;guide.showModal();};
 root.querySelector('[data-rqd-guide-close]').onclick=()=>guide.close();
 const rice=root.querySelector('[data-qc-sosoh]');
 if(rice){
  // Komponen juga dipakai proses aktif. Hanya halaman ini yang menata
  // bagian-bagiannya, tanpa menyalin field atau pengikat tindakan QC.
  const sections=[...rice.children].filter(n=>n.matches('section'));
  const panels={};
  for(const id of ['ringkasan','sampel','sesi','asal']){const p=document.createElement('div');p.id='qc-panel-'+id;p.dataset.rqdPanel=id;p.setAttribute('role','tabpanel');p.setAttribute('aria-labelledby','qc-tab-'+id);panels[id]=p;}
  for(const s of sections){const title=s.querySelector('h2')?.textContent.trim();const id=title==='Riwayat sampel dan hasil QC'?'sampel':title==='Estimasi waktu dan hasil tiap garapan'?'sesi':'ringkasan';panels[id].append(s);}
  const editor=panels.ringkasan.querySelector('[data-qc-editor]');
  if(editor){const card=document.createElement('section');card.className='riwayat-detail__card';card.append(editor);panels.sampel.prepend(card);}
  const create=panels.ringkasan.querySelector('[data-qc-baru]');
  const actions=root.querySelector('[data-rqd-proses-aksi]');
  if(actions){if(create)actions.prepend(create);rice.prepend(actions);}
  const riceTabs=root.querySelector('[data-rqd-beras-tabs]');rice.append(riceTabs);

  const origin=root.querySelector('[data-rqd-rice-origin]');if(origin){panels.asal.append(origin.content);origin.remove();}
  for(const id of ['sampel','sesi'])if(!panels[id].children.length){const p=document.createElement('p');p.className='riwayat-detail__card';p.textContent=id==='sampel'?'Belum ada sampel QC beras. Sampel boleh dicatat sebelum hasil timbang.':'Belum ada sesi QC aktif yang dapat dipetakan. Sampel yang dibatalkan tetap tersedia pada Sampel & hasil.';panels[id].append(p);}
  // Tautan ringkasan hanya mengungkap panel yang sama, bukan halaman/form baru.
  const shortcuts=document.createElement('section');shortcuts.className='riwayat-detail__card rhs-shortcuts';
  for(const [id,title] of [['sampel','Lihat sampel & hasil QC'],['sesi','Lihat sesi & pemetaan'],['asal','Buka asal & catatan']]){const a=document.createElement('a');const u=new URL(location.href);u.searchParams.set('tab_qc',id);a.href=u.pathname+u.search;a.textContent=title+' →';shortcuts.append(a);}
  panels.ringkasan.append(shortcuts);rice.append(...Object.values(panels));root.querySelector('[data-rqd-beras-tabs]').hidden=false;
  for(const a of root.querySelectorAll('[data-rqd-beras-tabs] a')){const u=new URL(location.href);u.searchParams.delete('buka');u.searchParams.delete('nilai');u.searchParams.set('tab_qc',a.id.slice(7));u.hash='';a.href=u.pathname+u.search;}
  for(const a of rice.querySelectorAll('a[href*="buka=batalkan_sampel_qc_sosoh"]')){const original=new URL(a.href,location.href),u=new URL(location.href);u.searchParams.set('tab_qc','sampel');for(const [k,v]of original.searchParams)u.searchParams.set(k,v);u.hash='';a.href=u.pathname+u.search;}

 }
 const tabs=[...root.querySelectorAll('.rhs-tabs [role=tab]')],panels=[...root.querySelectorAll('[data-rqd-panel]')];if(!tabs.length)return;
 function setRound(n){const rounds=[...root.querySelectorAll('.qc-history-round')];if(!rounds.length)return;
  const select=root.querySelector('#qc-putaran'),requested=Number(n);
  n=Number.isInteger(requested)?Math.min(rounds.length,Math.max(1,requested)):Number(select.value)||rounds.length;for(const r of rounds)r.hidden=Number(r.dataset.posisi)!==n;select.value=String(n);
  for(const a of tabs){const u=new URL(a.href,location.href);u.searchParams.set('putaran',String(n));a.href=u.pathname+u.search;}
  const pager=root.querySelector('.qc-pager');pager.replaceChildren();
  function control(label,value,enabled){const a=document.createElement(enabled?'a':'span');a.className='btn kontrol-paginasi__tombol';a.textContent=label;if(enabled){const u=new URL(location.href);u.searchParams.set('tab_qc','putaran');u.searchParams.set('putaran',String(value));a.href=u.pathname+u.search;}else a.setAttribute('aria-disabled','true');return a;}
  const position=document.createElement('span');position.className='kontrol-paginasi__posisi';position.textContent=n+' / '+rounds.length;pager.append(control('← Sebelumnya',n-1,n>1),position,control('Berikutnya →',n+1,n<rounds.length));
 }
 function show(id,url,focus=false){if(!panels.some(p=>p.dataset.rqdPanel===id))id='ringkasan';root.dataset.rqdSelected=id;
  for(const p of panels)p.hidden=p.dataset.rqdPanel!==id;
  for(const a of tabs){const active=a.id==='qc-tab-'+id;a.setAttribute('aria-selected',String(active));a.tabIndex=active?0:-1;if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  if(url){const selected=root.querySelector('#qc-putaran')?.value;if(selected&&!url.searchParams.has('putaran'))url.searchParams.set('putaran',selected);history.replaceState(history.state,'',url.pathname+url.search+url.hash);if(url.searchParams.has('putaran'))setRound(url.searchParams.get('putaran'));}
  if(focus)root.querySelector('[data-rqd-panel="'+id+'"]').scrollIntoView({block:'nearest'});
 }
 // Hanya tautan tab/putaran halaman ini. Klik dengan tombol pengubah dan
 // tindakan asli tetap mengikuti navigasi serta izin semula.
 root.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(!a||e.defaultPrevented||e.button!==0||e.ctrlKey||e.metaKey||e.altKey||e.shiftKey)return;const u=new URL(a.href,location.href);if(u.origin!==location.origin||u.pathname!==location.pathname||u.searchParams.has('buka')||!u.searchParams.has('tab_qc'))return;const id=u.searchParams.get('tab_qc');if(!panels.some(p=>p.dataset.rqdPanel===id))return;e.preventDefault();show(id,u);});
 root.querySelector('.rhs-tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const i=tabs.indexOf(e.target);if(i<0)return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].click();tabs[n].focus();});
 const picker=root.querySelector('.qc-picker');if(picker)picker.addEventListener('submit',e=>{e.preventDefault();const u=new URL(location.href);for(const [k,v]of new FormData(picker))u.searchParams.set(k,v);show('putaran',u);});
 // Pengikat QC asli menggulir ke editor saat dibuka. Tampilkan panel editor
 // lebih dahulu, termasuk ketika melengkapi sampel yang menunggu hasil.
 if(rice)rice.addEventListener('click',e=>{if(e.target.closest('[data-qc-baru],[data-qc-lengkapi]')){const u=new URL(location.href);u.searchParams.set('tab_qc','sampel');u.hash='';show('sampel',u);}},true);
 function restore(){const u=new URL(location.href);show(u.searchParams.get('tab_qc')||'ringkasan');setRound(u.searchParams.get('putaran')||root.querySelector('#qc-putaran')?.value);if(rice&&u.hash==='#qc-sosoh')show('sampel');}
 restore();if(window.PINDAH)PINDAH.pasang(window,'popstate',restore);else window.addEventListener('popstate',restore);
})();
