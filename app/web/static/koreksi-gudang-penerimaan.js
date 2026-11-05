/* Koreksi satu catatan penerimaan: tinjauan baca saja, satu konfirmasi, kunci retry tetap. */
(()=>{'use strict';
for(const root of document.querySelectorAll('[data-koreksi-gudang]')){
 if(root.dataset.ready)continue;root.dataset.ready='1';
 const endpoint='/api/actions/koreksi-gudang-penerimaan/'+root.dataset.tiket+'/'+root.dataset.jenis+'/'+root.dataset.id;
 const token=()=>document.getElementById('formulir-sesi')?.dataset.token||'';
 const key='koreksi-gudang:'+root.dataset.actor+':'+root.dataset.tiket+':'+root.dataset.jenis+':'+root.dataset.id+':'+token();
 const panel=root.querySelector('[data-kgp-panel]'),open=root.querySelector('[data-kgp-buka]');
 let ctx=null,plan=null,busy=false,leaving=false,state={warehouse_id:'',alasan:'',kunci:crypto.randomUUID(),dirty:false,uncertain:false,inflight:false};
 const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
 const kg=v=>v==null?'Belum diketahui':Number(v).toLocaleString('id-ID',{maximumFractionDigits:3})+' kg';
 function persist(){try{sessionStorage.setItem(key,JSON.stringify(state));}catch(_){}}
 try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved){state={...state,...saved};if(state.inflight){state.inflight=false;state.uncertain=true;}}}catch(_){}
 const btn=(text,fn,primary=false)=>{const b=el('button',text,'btn'+(primary?' btn--utama':''));b.type='button';b.onclick=fn;return b;};
 function note(text,error=false){const n=el('p',text,error?'kgp-error':'bm-meta');if(error)n.setAttribute('role','alert');else n.setAttribute('role','status');panel.append(n);}
 function shell(title){panel.replaceChildren(el('h3',title));panel.hidden=false;root.dataset.kgpOpen='';open.hidden=true;}
 async function call(url,body){
  if(window.SESIFORM&&!window.SESIFORM.periksa())throw Error('Sesi atau peran berubah. Buka kembali detail dengan akun yang benar; isian tetap tersimpan.');
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
  try{const r=await fetch(url,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':token()},body:body?JSON.stringify(body):undefined});
   let d;try{d=await r.json();}catch(_){throw Error('Balasan server belum lengkap.');}
   if(!r.ok){const e=Error(typeof d.detail==='string'?d.detail:'Permintaan belum dapat diproses. Periksa isian dan izin.');e.status=r.status;throw e;}return d;
  }finally{clearTimeout(timer);}
 }
 function body(){return {warehouse_id:Number(state.warehouse_id),alasan:state.alasan,dasar:ctx.dasar,kunci:state.kunci,pemeriksaan:plan?.pemeriksaan||'',konfirmasi:true};}
 function close(){if(busy)return;persist();panel.hidden=true;delete root.dataset.kgpOpen;open.hidden=false;open.textContent=state.dirty?'Lanjutkan koreksi gudang':'Koreksi gudang penerimaan';}
 function relations(container,items){for(const r of items){const row=el('p');if(r.url){const a=el('a',r.kode);a.href=r.url;row.append(a);}else row.append(el('strong',r.kode));row.append(el('span',' · '+(r.alasan||r.status||r.jenis)));container.append(row);}}
 async function load(){
  if(busy)return;busy=true;shell('Koreksi gudang penerimaan');note('Membaca gudang dan catatan terkait…');
  try{ctx=await call(endpoint);plan=null;render();if(state.uncertain)await status();}
  catch(e){note(e.message,true);panel.append(btn('Coba lagi',load),btn('Tutup',close));}
  finally{busy=false;}
 }
 function render(){
  shell('Koreksi gudang penerimaan');
  if(state.uncertain){note('Hasil simpan belum pasti. Periksa status sebelum mencoba kembali.');panel.append(btn('Periksa status simpan',status));return;}
  note(ctx.kode+' · '+ctx.gudang+' · versi '+ctx.versi);
  if(ctx.riwayat.length){const history=el('details');history.append(el('summary','Riwayat koreksi gudang ('+ctx.riwayat.length+')'));for(const h of ctx.riwayat){const p=h.hasil;history.append(el('p',p.sebelum.gudang+' → '+p.sesudah.gudang+' · versi '+p.sebelum.versi+' → '+p.sesudah.versi),el('p',p.alasan),el('p','Audit #'+h.id+' · petugas #'+h.petugas_id+' · '+new Date(h.waktu).toLocaleString('id-ID'),'bm-meta'));}panel.append(history);}
  if(ctx.relasi.length){const related=el('details');related.append(el('summary','Barang, silo & proses terkait ('+ctx.relasi.length+')'));relations(related,ctx.relasi);panel.append(related);}
  const form=el('form',null,'bm-form'),label=el('label','Gudang yang benar'),select=el('select');select.name='warehouse_id';select.required=true;select.setAttribute('aria-label','Gudang yang benar');select.append(new Option('Pilih gudang yang benar',''));
  for(const w of ctx.pilihan)select.append(new Option(w.label+(w.value===ctx.gudang_id?' · saat ini':''),w.value));
  if(state.warehouse_id&&!ctx.pilihan.some(w=>String(w.value)===String(state.warehouse_id)))select.append(new Option(state.warehouse_id+' · tidak tersedia, periksa kembali',state.warehouse_id));
  select.value=state.warehouse_id;select.onchange=()=>{state.warehouse_id=select.value;state.dirty=true;plan=null;persist();};label.append(select);
  const reasonLabel=el('label','Alasan koreksi'),reason=el('textarea');reason.name='alasan';reason.required=true;reason.maxLength=2000;reason.rows=3;reason.value=state.alasan;reason.setAttribute('aria-label','Alasan koreksi');reason.oninput=()=>{state.alasan=reason.value;state.dirty=true;plan=null;persist();};reasonLabel.append(reason);
  form.append(label,reasonLabel,el('p','Untuk memperbaiki pilihan gudang yang salah. Perpindahan barang fisik tetap melalui alur perpindahan.','bm-meta'));
  const actions=el('div',null,'bm-aksi'),review=el('button','Periksa dampak','btn btn--utama');review.type='submit';actions.append(review,btn('Tutup isian',close));form.append(actions);form.onsubmit=async e=>{e.preventDefault();if(busy||!form.reportValidity())return;await preview();};panel.append(form);
 }
 async function preview(){
  busy=true;for(const e of panel.querySelectorAll('input,select,textarea,button'))e.disabled=true;
  try{plan=await call(endpoint+'/periksa',body());review();}
  catch(e){plan=null;try{if(e.status===409)ctx=await call(endpoint);}catch(_){}render();note(e.message,true);}
  finally{busy=false;}
 }
 function review(){
  shell(plan.rencana.boleh_simpan?'Periksa sebelum menyimpan':'Koreksi belum dapat disimpan');const p=plan.rencana;
  const facts=el('dl',null,'bm-valores');for(const [label,value] of [['Gudang penerimaan',p.sebelum.gudang+' → '+p.sesudah.gudang],['Bobot penerimaan',kg(p.bobot)+' · tetap'],['Karung',p.karung==null?'Tidak berlaku / tidak tercatat':p.karung+' · tetap'],['Pemilik & barang fisik','Tetap'],['Versi pencatatan',p.sebelum.versi+' → '+p.sesudah.versi],['Alasan',p.alasan]]){const d=el('div');d.append(el('dt',label),el('dd',value));facts.append(d);}panel.append(facts,el('p',p.dampak,'bm-meta'));
  if(p.penghalang.length){const warn=el('div',null,'kgp-warning');relations(warn,p.penghalang);panel.append(warn,btn('Ubah isian',render));note('Belum ada perubahan pada stok atau catatan.');return;}
  const label=el('label',null,'kgp-confirm'),check=el('input');check.type='checkbox';label.append(check,el('span','Saya telah memeriksa lokasi barang dan catatan terkait.'));
  const save=btn('Simpan koreksi gudang',saveCorrection,true);save.disabled=true;check.onchange=()=>{save.disabled=!check.checked;};panel.append(label);const actions=el('div',null,'bm-aksi');actions.append(save,btn('Ubah isian',render));panel.append(actions);note('Izin, saldo, relasi, dan versi diperiksa ulang saat menyimpan.');
 }
 function result(d){
  state={...state,dirty:false,inflight:false,uncertain:false};try{sessionStorage.removeItem(key);}catch(_){}shell('Gudang penerimaan dikoreksi');note(d.hasil.sebelum.gudang+' → '+d.hasil.sesudah.gudang+'. Bobot, pemilik, silo, dan hasil proses tetap.');note('Audit #'+d.peristiwa_id+' · versi '+d.hasil.sebelum.versi+' → '+d.hasil.sesudah.versi);
  panel.append(btn('Lihat detail terbaru',()=>{leaving=true;sessionStorage.removeItem(key);location.reload();},true));
 }
 async function saveCorrection(){
  if(busy||!plan?.rencana.boleh_simpan)return;busy=true;state.inflight=true;persist();for(const e of panel.querySelectorAll('button,input'))e.disabled=true;
  try{result(await call(endpoint+'/simpan',body()));}
  catch(e){state.inflight=false;if(!e.status||e.status>=500){state.uncertain=true;persist();render();await status();}else{plan=null;persist();try{ctx=await call(endpoint);}catch(_){}render();note(e.message,true);}}
  finally{busy=false;}
 }
 async function status(){
  try{const d=await call('/api/actions/koreksi-gudang-penerimaan/status/'+encodeURIComponent(state.kunci));if(d.tercatat){result(d);return;}
   state.inflight=false;state.uncertain=true;persist();shell('Periksa hasil penyimpanan');note('Koreksi belum ditemukan pada pembacaan ini. Permintaan sebelumnya mungkin masih diproses. Jangan langsung mengirim ulang.');panel.append(btn('Baca status lagi',status),btn('Baca data & periksa ulang',async()=>{state.uncertain=false;persist();busy=false;await load();}));
  }catch(e){state.uncertain=true;persist();shell('Status simpan belum terbaca');note(e.message,true);panel.append(btn('Coba baca status lagi',status));}
 }
 open.onclick=load;if(state.dirty||state.uncertain)open.textContent='Lanjutkan koreksi gudang';
 window.addEventListener('beforeunload',e=>{if(root.isConnected&&!leaving&&(state.dirty||state.uncertain||busy)){persist();e.preventDefault();e.returnValue='';}});
 document.addEventListener('click',e=>{if(!root.isConnected||e.defaultPrevented||leaving||(!state.dirty&&!state.uncertain&&!busy)||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(!a||a.target||a.hasAttribute('download')||a.getAttribute('href').startsWith('#'))return;e.preventDefault();e.stopImmediatePropagation();persist();panel.hidden=false;shell('Isian koreksi belum selesai');note(state.uncertain?'Periksa status penyimpanan sebelum berpindah.':'Isian tersimpan sementara di perangkat. Berpindah halaman tidak menyimpan koreksi.');panel.append(btn('Tetap di isian',()=>{if(plan)review();else render();}));if(!busy&&!state.uncertain)panel.append(btn('Lanjut dengan isian tersimpan',()=>{leaving=true;location.assign(a.href);}));else panel.append(btn('Periksa status simpan',status));},true);
}
})();
