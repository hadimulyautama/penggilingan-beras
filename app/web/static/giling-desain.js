/* Penyajian giling aktif. Node editor asli dipindahkan, bukan dibuat ulang.
   Seluruh mutasi, pemeriksaan, draf dan pemulihan tetap milik giling-ringkas. */
(function(){
'use strict';
const root=document.querySelector('[data-giling-ringkas]');if(!root||root.dataset.desainSiap)return;root.dataset.desainSiap='1';
const body=root.querySelector('[data-proses-isi]'),guide=root.querySelector('#gr-panduan');
const tabs=[['ringkasan','Ringkasan'],['bahan','Bahan & silo'],['hasil','Hasil PK'],['qc','QC'],['riwayat','Riwayat']];
const initial=new URL(location.href).searchParams.get('tab_detail');
let selected=tabs.some(t=>t[0]===initial)?initial:({hasil_giling:'hasil',tutup_silo_giling:'bahan',tambah_silo_giling:'bahan',qc_giling:'qc'}[root.dataset.buka]||'ringkasan');
let output=null,panels={};
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const kg=v=>v==null?'Belum tersedia':Number(v).toLocaleString('id-ID',{maximumFractionDigits:3})+' kg';
const button=(text,fn,cls='btn')=>{const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;};
function show(tab,focus=false){
 selected=tab;root.dataset.tabGiling=tab;
 // Satu formulir kumulatif yang sama tersedia langsung di Ringkasan / Hasil PK.
 if(output&&panels[tab]&&['ringkasan','hasil'].includes(tab)){
  if(tab==='ringkasan')panels[tab].querySelector('[data-gr-output-slot]').append(output);
  else panels[tab].prepend(output);
 }
 for(const p of Object.values(panels))p.hidden=p.dataset.srPanel!==tab;
 body.querySelectorAll('[data-sr-tab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.srTab===tab)));
 if(focus)panels[tab]?.scrollIntoView({block:'nearest'});
}
function pair(box,label,value){const r=el('div',null,'sr-pair');r.append(el('dt',label),el('dd',value));box.append(r);}
function decorate(){
 const d=root.pfGilingData;if(!d?.aktif){root.classList.remove('sr-redesign','gr-redesign');output=null;panels={};return;}
 root.classList.add('sr-redesign','gr-redesign');const ui=root.pfGilingPresentationState||{};
 const locked=!!(ui.busy||ui.uncertain||ui.action||ui.review),head=body.querySelector('header');if(!head)return;
 const h1=head.querySelector('h1');if(h1){const code=el('p',h1.textContent,'sr-design-code');h1.textContent='Penggilingan aktif';h1.after(code);}
 const back=el('a','← Kembali ke Pekerjaan','sr-design-back');back.href=root.dataset.kembali||'/pekerjaan?tab=berjalan';head.prepend(back);
 const tools=el('div',null,'sr-design-tools');tools.append(button('ⓘ Panduan',()=>guide?.showModal(),'btn btn--kecil'));
 const menu=el('details',null,'sr-design-menu'),sum=el('summary','⋮','btn');sum.setAttribute('aria-label','Tindakan proses');menu.append(sum);
 const menuBody=el('div',null,'sr-design-menu-body');menuBody.append(button('ⓘ Panduan',()=>{menu.open=false;guide?.showModal()}),button('Baca status terbaru',()=>{menu.open=false;root.querySelector('[data-terbaru]').click()}),button('Print detail',()=>{menu.open=false;window.print()}));menu.append(menuBody);tools.append(menu);head.append(tools);
 const actions=[...body.children].find(n=>n.classList.contains('sr-actions'));if(actions){actions.classList.add('sr-design-actions');for(const b of actions.querySelectorAll('button')){if(b.textContent==='Selesaikan penggilingan')b.textContent='Periksa selesai';else if(b.textContent==='Hentikan sementara')b.textContent='Jeda mesin';else if(b.textContent==='Lanjutkan penggilingan')b.textContent='Lanjutkan proses';}}
 const board=body.querySelector('.sr-board');output=null;panels={};
 // Penyelesaian adalah formulir pemeriksaan utuh; jangan menyembunyikan langkahnya.
 if(!board)return;
 const metrics=body.querySelector('.sr-metrics'),sources=board.querySelector('#sumber'),qc=board.querySelector('#qc'),history=board.querySelector('details.sr-card');
 output=board.querySelector('#hasil');
 const nav=el('nav',null,'sr-design-tabs');nav.setAttribute('aria-label','Detail penggilingan');nav.setAttribute('role','tablist');
 for(const [key,label]of tabs){const b=button(label,()=>show(key),'');b.disabled=locked;b.dataset.srTab=key;b.id='gr-tab-'+key;b.setAttribute('role','tab');b.setAttribute('aria-controls','gr-panel-'+key);nav.append(b);const p=el('section',null,'sr-design-panel');p.id='gr-panel-'+key;p.dataset.srPanel=key;p.setAttribute('role','tabpanel');p.setAttribute('aria-labelledby',b.id);panels[key]=p;}
 nav.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const buttons=[...nav.querySelectorAll('button:not(:disabled)')];if(!buttons.length)return;const i=buttons.indexOf(document.activeElement),next=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;e.preventDefault();show(buttons[next].dataset.srTab);buttons[next].focus();});
 (actions||head).after(nav);
 const overview=el('section',null,'sr-card sr-design-overview'),title=el('div',null,'sr-design-overview-title');title.append(el('h2','Hasil penggilingan'),el('span',d.bobot_final?'Bobot sumber final':'Bobot sumber sementara','sr-status'));overview.append(title);
 // Nilai asli tetap dipakai; tidak ada rumus baru atau dugaan sisa per lot.
 if(metrics){metrics.classList.add('gr-design-metrics');overview.append(metrics);}
 overview.append(el('p','Rendemen memakai catatan operator dan bobot acuan dari sumber. Kepastian bobot mengikuti sumber proses; sisa tiap silo tetap diperiksa tersendiri.','sr-help'));
 panels.ringkasan.append(overview);const slot=el('div');slot.dataset.grOutputSlot='';panels.ringkasan.append(slot);
 const stockSummary=el('section',null,'sr-card gr-design-stock');stockSummary.append(el('h2','Stok PK yang berlaku'));const numbers=el('dl');pair(numbers,'Dasar stok yang berlaku',kg(d.dasar_stok));pair(numbers,'PK tersedia',kg(d.stok_sebelum));stockSummary.append(numbers,el('p',d.terverifikasi==null?'Belum ada verifikasi Admin. Dasar stok mengikuti layanan stok.':'Verifikasi Admin '+kg(d.terverifikasi)+' menjadi dasar stok. Catatan operator bukan mutasi tambahan.','sr-help'));
 const stockDetail=output?.querySelector(':scope > details');if(stockDetail){const copy=stockDetail.cloneNode(true);copy.open=false;copy.querySelector('summary').textContent='Lihat perhitungan stok lengkap';stockSummary.append(copy);}panels.ringkasan.append(stockSummary);
 if(output)panels.hasil.append(output);
 if(sources)panels.bahan.append(sources);
 if(qc)panels.qc.append(qc);
 if(history){history.open=true;panels.riwayat.append(history);}
 const facts=el('section',null,'sr-card');facts.append(el('h2','Identitas & waktu proses'));const dl=el('dl');for(const [name,value]of [['Kode proses',d.kode_proses],['Pemilik',d.pemilik+' · '+d.kepemilikan],['Gudang',d.gudang],['Pesanan jasa',d.pesanan||'Tidak terkait pesanan jasa'],['Mulai',d.waktu.mulai?new Date(d.waktu.mulai).toLocaleString('id-ID'):'Tidak tercatat'],['Durasi proses',d.waktu.durasi],['Durasi efektif',d.waktu.aktif],['Total jeda',d.waktu.jeda]])pair(dl,name,value);facts.append(dl);panels.riwayat.prepend(facts);
 board.replaceWith(...Object.values(panels));
 const forced=ui.action==='qc'?'qc':['bebaskan','mix'].includes(ui.action)?'bahan':ui.action==='hasil'&&!['ringkasan','hasil'].includes(selected)?'hasil':null;
 show(forced||selected);
}
root.addEventListener('pf:detail-render',decorate);
root.addEventListener('click',e=>{
 const a=e.target.closest('a[href^="#"]');if(a){const h=a.getAttribute('href');if(h==='#hasil')show('hasil');if(h==='#sumber')show('bahan');if(h==='#qc')show('qc');}
 // Kembali dari langkah selesai ke isian asli sebelum handler lama merender ulang.
 if(e.target.closest('button')?.textContent==='Periksa isian PK')selected='hasil';
},true);
if(guide){guide.querySelector('[data-gr-guide-close]').onclick=()=>guide.close();guide.addEventListener('click',e=>{if(e.target===guide){const r=guide.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)guide.close()}});}
})();
