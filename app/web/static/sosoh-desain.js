/* Susun ulang DOM pembaca lama. Editor, draf, pemeriksaan dan mutasi tetap
   milik sosoh-ringkas/qc-sosoh/koreksi-di-detail. QC tidak dibangun ulang. */
(function(){
'use strict';
const root=document.querySelector('[data-sosoh-ringkas]');if(!root||root.dataset.desainSiap)return;root.dataset.desainSiap='1';
const body=root.querySelector('[data-proses-isi]'),qc=root.querySelector('[data-sr-qc]'),pack=root.querySelector('[data-sr-pack]'),guide=root.querySelector('#sr-panduan');
const tabs=[['ringkasan','Ringkasan'],['bahan','Bahan & silo'],['hasil','Hasil'],['qc','QC'],['riwayat','Riwayat']];
let selected=location.hash==='#qc-sosoh'?'qc':new URL(location.href).searchParams.get('tab_detail')||'ringkasan';if(!tabs.some(t=>t[0]===selected))selected='ringkasan';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const kg=v=>v==null?'Belum tersedia':Number(v).toLocaleString('id-ID',{maximumFractionDigits:3})+' kg';
const button=(text,fn,cls='btn')=>{const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;};
function show(tab,focus=false){selected=tab;root.dataset.tabSosoh=tab;
 for(const p of body.querySelectorAll('[data-sr-panel]'))p.hidden=p.dataset.srPanel!==tab;
 if(qc)qc.hidden=tab!=='qc';
 body.querySelectorAll('[data-sr-tab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.srTab===tab)));
 if(focus){const p=tab==='qc'?qc:body.querySelector('[data-sr-panel="'+tab+'"]');p?.scrollIntoView({block:'nearest'});}
}
function sourceRows(box,u,d){const g=d.kelompok_sumber?.find(g=>String(g.id)===String(u.id));
 const detail=el('details',null,'sr-source-details');detail.dataset.srSourceDetails='';
 detail.append(el('summary','Catatan sumber'));
 const note=el('p','Rincian asal menjelaskan isi bahan. Bobot catatan asal tidak ditambahkan lagi ke total masuk pada siklus ini.','sr-help');detail.append(note);
 if(g){
  if(g.bahan?.length){const types=el('dl',null,'sr-source-composition');for(const b of g.bahan){const r=el('div');r.append(el('dt',b.nama),el('dd',b.berat||'Belum diketahui'));types.append(r);}detail.append(types);}
  if(g.sumber?.length){const table=el('table',null,'sr-source-table');table.setAttribute('aria-label','Asal isi '+u.silo+' · siklus #'+u.id);const head=el('thead'),hr=el('tr');for(const t of ['Catatan asal','Bobot catatan asal','Waktu / keterangan'])hr.append(el('th',t));head.append(hr);table.append(head);const tb=el('tbody');
   for(const s of g.sumber){const r=el('tr');for(const [i,text] of [s.nama,s.berat||'Tidak dipisahkan',s.ket||'Belum tercatat'].entries()){const c=el(i===0?'th':'td',text);if(i===0)c.scope='row';else c.dataset.label=i===1?'Bobot catatan asal':'Waktu / keterangan';r.append(c);}tb.append(r);}table.append(tb);detail.append(table);
  }else detail.append(el('p','Asal lot tidak tercatat atau tersedia sebagai komposisi bahan di atas.','sr-help'));
 }
 const entries=el('div',null,'sr-source-entries');entries.dataset.srEntryList='';detail.append(entries);
 detail.addEventListener('toggle',()=>{root.dataset['sumber'+u.id]=detail.open?'1':'0'});detail.open=root.dataset['sumber'+u.id]==='1';box.append(detail);
}
// Lembar operator memakai node, editor, dan pemeriksaan yang sama. Tidak ada
// endpoint penulisan atau aturan stok kedua, dan tidak ada kontrol untuk menaikkan peran.
const operator=root.dataset.layout==='operator';
let qcFold=null,packFold=null;

function fold(node,label,key){
 const box=el('details',null,'sr-card sr-full');box.dataset.srFold=key;
 box.append(el('summary',label),node);
 box.open=root.dataset[key]==='1';
 box.addEventListener('toggle',()=>{root.dataset[key]=box.open?'1':'0';});
 return box;
}
let previewTimer=null,previewSequence=0;
function outputBalance(d,outputs,compact=false){
 if(!outputs)return;
 clearTimeout(previewTimer);const generation=++previewSequence;
 const summary=el('section',null,'sr-note sr-work-result-balance');summary.setAttribute('aria-live','polite');
 if(compact)summary.classList.add('sr-admin-result-balance');
 const status=el('strong'),basis=el('p',null,'sr-help'),totals=el('p'),gap=el('p');summary.append(status,basis,totals,gap);(outputs.querySelector('.sr-metrics')||outputs.querySelector('.sr-help')).after(summary);
 const percent=v=>v==null?'Belum dapat dihitung':Number(v).toLocaleString('id-ID',{maximumFractionDigits:2})+'%';
 const marks=new Map();for(const row of outputs.querySelectorAll('[data-kb-output]')){const mark=el('small',null,'sr-work-percent');row.firstElementChild.append(mark);marks.set(row.dataset.kbOutput,mark);}
 function paint(value,draft=false){
  status.textContent=draft?'Pratinjau isian · belum disimpan':'Neraca hasil tercatat';
  basis.textContent='Dasar: '+kg(value.bahan_kg)+(value.sementara?' · sementara':' · bahan terpakai');
  for(const h of value.hasil)if(marks.has(h.jenis)){const old=d.neraca_lembar.hasil.find(x=>x.jenis===h.jenis);marks.get(h.jenis).textContent=h.kg==null?'Persentase belum tersedia':(draft&&old?.kg!==h.kg?(old?.kg==null?'Belum dicatat':percent(old.persen))+' → '+percent(h.persen)+' · pratinjau':percent(h.persen))+' dari bahan';}
  totals.textContent='Total hasil '+(draft?'tercatat: '+kg(d.neraca_lembar.total_kg)+' · '+percent(d.neraca_lembar.total_persen)+' → pratinjau: ':'tercatat: ')+kg(value.total_kg)+' · '+percent(value.total_persen);
  gap.textContent=(value.sementara?'Susut/selisih sementara: ':'Susut/selisih akhir: ')+(draft?kg(d.neraca_lembar.susut_kg)+' · '+percent(d.neraca_lembar.susut_persen)+' → pratinjau: ':'')+kg(value.susut_kg)+' · '+percent(value.susut_persen);
 }
 function pending(text){paint(d.neraca_lembar);status.textContent=text;totals.textContent+=' · pratinjau menunggu';gap.textContent+=' · pratinjau menunggu';}
 function inputs(){return [...outputs.querySelectorAll('[data-kb-output] input')].map(input=>({jenis:input.closest('[data-kb-output]').dataset.kbOutput,total:input.value}));}
 function changed(rows){return rows.filter(h=>h.total===''||Number(h.total)!==(d.hasil.find(x=>x.jenis===h.jenis)?.kg??0));}
 async function preview(){
  const rows=changed(inputs());if(!rows.length){paint(d.neraca_lembar);return;}
  if(rows.some(h=>h.total===''||!Number.isFinite(Number(h.total))||Number(h.total)<0)){pending('Periksa isian hasil · pratinjau belum tersedia');return;}
  const snapshot=JSON.stringify(inputs());pending('Memeriksa pratinjau neraca · belum disimpan');
  try{
   const response=await fetch('/api/actions/sosoh-ringkas/'+encodeURIComponent(d.kode_proses)+'/neraca/pratinjau',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':document.getElementById('formulir-sesi')?.dataset.token||''},body:JSON.stringify({dasar:d.dasar,hasil:rows.map(h=>({jenis:h.jenis,total:Number(h.total)}))})});
   const value=await response.json();if(generation!==previewSequence||snapshot!==JSON.stringify(inputs()))return;
   if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'Pratinjau belum tersedia.');
   paint(value,true);
  }catch(e){if(generation===previewSequence&&snapshot===JSON.stringify(inputs()))pending(e.message+' Isian belum disimpan.');}
 }
 paint(d.neraca_lembar);
 for(const input of outputs.querySelectorAll('[data-kb-output] input'))input.addEventListener('input',()=>{clearTimeout(previewTimer);pending('Isian berubah · menunggu pratinjau');previewTimer=setTimeout(preview,450);});
 if(changed(inputs()).length)previewTimer=setTimeout(preview,0);
}
function compactSources(sources,d){
 const heading=sources.querySelector('h2');
 const add=[...sources.children].find(n=>n.tagName==='BUTTON');
 const header=el('div',null,'sr-work-source-heading');
 const toggle=button('',()=>{const open=content.hidden;content.hidden=!open;root.dataset.siloTerbuka=open?'1':'0';toggle.setAttribute('aria-expanded',String(open));toggle.textContent=(open?'▾ ':'▸ ')+'Bahan & silo';});
 toggle.classList.add('sr-work-source-toggle');toggle.setAttribute('aria-controls','sr-work-silos');
 header.append(toggle);if(add)header.append(add);heading?.replaceWith(header);
 const content=el('div');content.id='sr-work-silos';content.hidden=root.dataset.siloTerbuka==='0';toggle.setAttribute('aria-expanded',String(!content.hidden));toggle.textContent=(content.hidden?'▸ ':'▾ ')+'Bahan & silo';
 for(const u of d.sumber){
  const box=[...sources.querySelectorAll('[data-kb-cycle]')].find(n=>n.dataset.kbCycle===String(u.id));if(!box)continue;
  const head=box.querySelector('.sr-context'),name=head.querySelector('strong'),status=head.querySelector('.sr-status');
  const details=el('details',null,'sr-work-cycle-details');details.dataset.srCycleDetails=String(u.id);details.append(el('summary','Rincian · siklus #'+u.id));details.open=root.dataset['siklus'+u.id]==='1';details.addEventListener('toggle',()=>{root.dataset['siklus'+u.id]=details.open?'1':'0';});
  const release=[...box.children].find(n=>n.tagName==='BUTTON');
  for(const node of [...box.children])if(node!==head&&node!==release)details.append(node);
  const identity=el('div',null,'sr-work-silo-identity');identity.append(name);
  const weight=u.awal==null||u.tambahan==null?null:u.awal+u.tambahan;
  identity.append(el('small','Bahan siklus '+kg(weight)));
  head.replaceChildren(identity);if(release){release.textContent='Bebaskan';release.setAttribute('aria-label','Bebaskan '+u.silo+' · siklus #'+u.id);head.append(release);}else if(status)head.append(status);
  box.append(details);content.append(box);
 }
 for(const node of [...sources.children])if(node!==header){if(node.classList.contains('sr-help'))node.remove();else content.append(node);}
 sources.append(content);
}
function worksheet(d){
 const ui=root.pfSosohPresentationState||{},locked=ui.busy||ui.uncertain||ui.action||ui.review;
 root.classList.add('sr-redesign','sr-worksheet');
 const head=body.querySelector('header');if(!head)return;
 const h1=head.querySelector('h1');if(h1){const code=el('p',h1.textContent,'sr-design-code');h1.textContent=d.aktif?'Penyosohan aktif':'Penyosohan selesai';h1.after(code);}
 const help=button('ⓘ Panduan',()=>guide?.showModal(),'btn btn--kecil');help.classList.add('sr-work-guide');head.append(help);
 const metrics=body.querySelector('.sr-metrics');
 const board=body.querySelector('.sr-board');
 // Pemeriksaan akhir tetap satu layar fokus; hasil kerja tidak diulang.
 if(!board){
  if(qcFold)qcFold.hidden=true;if(packFold)packFold.hidden=true;if(qc)qc.hidden=true;
  const n=d.neraca_lembar,summary=el('p',null,'sr-note');summary.dataset.srFinishBalance='';
  summary.textContent='Susut/selisih sementara tercatat: '+kg(n.susut_kg)+' · '+(n.susut_persen==null?'Belum dapat dihitung':Number(n.susut_persen).toLocaleString('id-ID',{maximumFractionDigits:2})+'%');
  body.querySelector('[data-action-panel]')?.prepend(summary);return;
 }
 const sources=board.querySelector('#sumber');
 const outputs=board.querySelector('#hasil');
 if(outputs){
  outputs.querySelector('h2').textContent=d.aktif?'Catat hasil & neraca':'Hasil akhir & neraca';
  metrics?.remove();
  outputBalance(d,outputs);
  for(const help of [...outputs.querySelectorAll(':scope>.sr-help')].slice(1))help.remove();
 }
 if(sources){for(const u of d.sumber){const box=[...sources.querySelectorAll('[data-kb-cycle]')].find(n=>n.dataset.kbCycle===String(u.id));if(box)sourceRows(box,u,d);}compactSources(sources,d);}
 const actions=[...body.children].find(n=>n.classList.contains('sr-actions'));
 const balance=board.querySelector('.sr-full'),history=board.querySelector('.sr-full:last-child');
 if(actions){
  const finish=actions.firstElementChild;
  const completion=el('section',null,'sr-card sr-full sr-work-finish');completion.dataset.srWorkFinish='';
  completion.append(el('h2','Kesiapan selesai'),el('p',d.penghalang||'Pemeriksaan awal terpenuhi. Periksa data terbaru sebelum menyelesaikan.','sr-help'));
  finish.textContent='Periksa & selesaikan penyosohan';finish.classList.add('btn--utama');completion.append(finish);
  board.insertBefore(completion,balance);
  for(const b of [...actions.querySelectorAll('button'),finish])b.disabled=b.disabled||!!locked;
  // Jeda tetap di dekat identitas; tidak mencatat hasil maupun melepas silo.
  head.append(actions);
 }
 if(qc){
  if(!qcFold)qcFold=fold(qc,'QC beras · sampel & hasil pemeriksaan','qcTerbuka');
  qc.hidden=false;qcFold.hidden=false;
  if(location.hash==='#qc-sosoh'||new URL(location.href).searchParams.get('tab_detail')==='qc')qcFold.open=true;
  board.insertBefore(qcFold,balance);
 }
 if(pack){if(!packFold)packFold=pack;packFold.classList.add('sr-full');packFold.hidden=false;board.insertBefore(packFold,balance);}
 // Rincian neraca tetap di bagian pencatatan yang sama, tanpa pindah tab.
 if(balance&&outputs)outputs.append(balance);
 // Semua putaran QC, jejak bahan/hasil dan audit tetap dapat dibuka.
 if(history)history.dataset.srWorkHistory='';
}
function decorate(){const d=root.pfSosohData;if(operator&&d){worksheet(d);return;}if(!d?.aktif){if(qc)qc.hidden=false;if(pack){pack.hidden=false;if(!pack.isConnected)root.append(pack)}root.classList.remove('sr-redesign');return;}
 const ui=root.pfSosohPresentationState||{};const locked=ui.busy||ui.uncertain||ui.action||ui.review;root.classList.add('sr-redesign');const head=body.querySelector('header');if(!head)return;
 const h1=head.querySelector('h1');if(h1){const code=el('p',h1.textContent,'sr-design-code');h1.textContent='Penyosohan aktif';h1.after(code);}
 const back=el('a','← Kembali ke Pekerjaan','sr-design-back');back.href=root.dataset.kembali||'/pekerjaan?tab=berjalan';head.prepend(back);
 const tools=el('div',null,'sr-design-tools');tools.append(button('ⓘ Panduan',()=>guide?.showModal(),'btn btn--kecil'));
 const menu=el('details',null,'sr-design-menu');const sum=el('summary','⋮','btn');sum.setAttribute('aria-label','Tindakan proses');menu.append(sum);const menuBody=el('div',null,'sr-design-menu-body');menuBody.append(button('ⓘ Panduan',()=>{menu.open=false;guide?.showModal()}),button('Baca status terbaru',()=>{menu.open=false;root.querySelector('[data-terbaru]').click()}),button('Print detail',()=>{menu.open=false;window.print()}));menu.append(menuBody);tools.append(menu);head.append(tools);
 const board=body.querySelector('.sr-board');if(!board){if(qc)qc.hidden=true;return;}
 const outputs=board.querySelector('#hasil'),sources=board.querySelector('#sumber');
 const history=board.querySelector('.sr-full:last-child'),balance=board.querySelector('.sr-full');
 const metrics=body.querySelector('.sr-metrics');
 const actions=[...body.children].find(n=>n.classList.contains('sr-actions'));
 if(actions){actions.classList.add('sr-design-actions');if(outputs){actions.prepend(button('Catat hasil',()=>{show('hasil',true);outputs.querySelector('input:not(:disabled)')?.focus()},'btn btn--utama'));actions.firstElementChild.disabled=!!locked||!ui.can;for(const b of [...actions.children].slice(1))b.classList.remove('btn--utama');}}
 const nav=el('nav',null,'sr-design-tabs');nav.setAttribute('aria-label','Detail penyosohan');nav.setAttribute('role','tablist');
 const panels={};for(const [key,label]of tabs){const b=button(label,()=>show(key),'');b.disabled=!!locked;b.dataset.srTab=key;b.id='sr-tab-'+key;b.setAttribute('role','tab');b.setAttribute('aria-controls',key==='qc'?'sr-qc-panel':'sr-panel-'+key);nav.append(b);if(key!=='qc'){const p=el('section',null,'sr-design-panel');p.id='sr-panel-'+key;p.dataset.srPanel=key;p.setAttribute('role','tabpanel');p.setAttribute('aria-labelledby',b.id);panels[key]=p;}}
 nav.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const buttons=[...nav.querySelectorAll('button:not(:disabled)')];if(!buttons.length)return;const current=buttons.indexOf(document.activeElement);let index=e.key==='Home'?0:e.key==='End'?buttons.length-1:(current+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;e.preventDefault();show(buttons[index].dataset.srTab);buttons[index].focus();});
 head.after(...(actions?[actions]:[]),nav);
 const overview=el('section',null,'sr-card sr-design-overview');const title=el('div',null,'sr-design-overview-title');title.append(el('h2','Neraca sementara'),el('span','Belum final','sr-status'));overview.append(title);
 const mass=el('div',null,'sr-design-mass');const basis=d.sisa_lengkap?d.bahan:(d.sementara?kg(d.sementara.bahan):d.bahan),gap=d.sisa_lengkap?d.selisih:d.sementara?.selisih;
 for(const [label,value,small]of [[d.sisa_lengkap?'Bahan terpakai':'Bahan proses · sementara',basis,d.sisa_lengkap?'Sisa seluruh siklus sudah dicatat':'Sisa seluruh siklus belum lengkap'],['Seluruh hasil tercatat',kg(d.total),'Total hasil produksi proses ini'],['Selisih sementara',kg(gap),'Belum berarti susut final']]){const cell=el('div');cell.append(el('span',label),el('strong',value));if(label==='Selisih sementara')cell.append(el('small',gap==null||d.neraca_lembar.susut_persen==null?'Persentase belum dapat dihitung':Number(d.neraca_lembar.susut_persen).toLocaleString('id-ID',{maximumFractionDigits:2})+'% dari bahan'));cell.append(el('small',small));mass.append(cell);}overview.append(mass);
 if(metrics){metrics.classList.add('sr-original-metrics');if(metrics.firstElementChild?.querySelector('strong')?.textContent===basis)metrics.firstElementChild.remove();overview.append(metrics);}
 overview.append(el('p','Selisih sementara dapat mencakup bahan di mesin dan hasil yang belum dicatat. Rendemen dan susut akhir mengikuti kepastian sumber serta pencatatan proses.','sr-help'));
 panels.ringkasan.append(overview);if(balance)panels.ringkasan.append(balance);
 const links=el('section',null,'sr-card sr-design-shortcuts');links.append(el('h2','Pemeriksaan berikutnya'));
 for(const [key,label,info]of [['bahan','Bahan & silo',d.sumber.filter(u=>u.sisa==null).length+' siklus masih terikat'],['hasil','Rincian hasil',d.hasil.filter(h=>h.tercatat).length+' jenis sudah tercatat'],['qc','QC beras','Sampel, hasil lab dan estimasi sesi'],['riwayat','Riwayat & waktu','Pencatatan, jeda, alasan dan koreksi']]){const b=button('',()=>show(key,true),'sr-shortcut');const text=el('span',label);text.append(el('small',info));b.append(text,el('span','›'));links.append(b);}panels.ringkasan.append(links);
 if(sources){panels.bahan.append(sources);for(const u of d.sumber){const box=[...sources.querySelectorAll('[data-kb-cycle]')].find(n=>n.dataset.kbCycle===String(u.id));if(box)sourceRows(box,u,d);}}
 if(outputs){outputBalance(d,outputs,true);panels.hasil.append(outputs);if(pack){pack.hidden=false;panels.hasil.append(pack);}}
 if(history&&history!==balance){history.open=true;panels.riwayat.append(history);}
 const facts=el('section',null,'sr-card');facts.append(el('h2','Identitas & waktu proses'));const dl=el('dl');for(const [name,value]of d.fakta||[]){const row=el('div',null,'sr-pair');row.append(el('dt',name),el('dd',value));dl.append(row);}facts.append(dl);panels.riwayat.prepend(facts);
 // Panel aksi yang sedang dibuka menentukan tab; tak pernah menyembunyikan pemeriksaan.
 const pending=board.querySelector('[data-action-panel],[data-review]');let forced=pending?.closest('#hasil')?'hasil':pending?.closest('#sumber')?'bahan':null;
 board.replaceWith(...Object.values(panels));
 if(qc){qc.id='sr-qc-panel';qc.setAttribute('role','tabpanel');qc.setAttribute('aria-labelledby','sr-tab-qc');}
 show(forced||selected);
}
root.addEventListener('pf:detail-render',decorate);
root.addEventListener('click',e=>{if(e.target.closest('[data-qc-baru]')){if(operator&&qcFold)qcFold.open=true;else show('qc');}},true);
root.addEventListener('click',e=>{const link=e.target.closest('a[href^="#"]');if(!link)return;const hash=link.getAttribute('href');if(operator){if(hash==='#qc-sosoh'&&qcFold)qcFold.open=true;return;}if(hash==='#hasil')show('hasil');if(hash==='#sumber')show('bahan');if(hash==='#qc-sosoh')show('qc');});
if(guide){guide.querySelector('[data-sr-guide-close]').onclick=()=>guide.close();guide.addEventListener('click',e=>{if(e.target===guide){const r=guide.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)guide.close()}});}
})();
