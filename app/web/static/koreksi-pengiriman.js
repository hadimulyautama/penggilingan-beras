(function () {
  'use strict';
  const root=document.querySelector('[data-koreksi-selesai]');if(!root||root.dataset.ready)return;root.dataset.ready='1';
  const initial=JSON.parse(document.getElementById('kp-awal').textContent),f=root.querySelector('[data-form]'),msg=root.querySelector('[data-pesan]'),area=root.querySelector('[data-rencana]'),save=root.querySelector('[data-simpan]'),status=root.querySelector('[data-status]');
  const base='/api/actions/koreksi-pengiriman/'+root.dataset.id,space='koreksi-selesai:'+root.dataset.actor+':'+root.dataset.id;
  let key=root.dataset.key,plan=null,busy=false,uncertain=false,done=false,catalogVersion=0;
  function el(tag,text){const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;}
  function message(s){msg.textContent=s;}
  function option(select,value,label){const o=el('option',label);o.value=String(value);select.append(o);}
  const holder=root.querySelector('[data-items]');
  initial.barang.forEach(b=>{const row=el('section');row.className='pp-barang';row.dataset.item=b.id;
    row.append(el('h2',b.nama),el('p','Efektif sekarang: '+(b.jumlah===''?'jumlah belum tercatat':b.jumlah+' '+b.satuan)+' · '+b.berat_kg+' kg'));
    const label=el('label','Barang/sumber yang benar'),pick=el('select');pick.name='pilih';pick.className='fld';option(pick,b.pilih,b.nama+' · sumber sekarang');label.append(pick);
    const qtyLabel=el('label','Total yang benar'),qty=el('input');qty.name='jumlah';qty.type='number';qty.min='0';qty.step=b.satuan==='karung'?'1':'0.01';qty.value=b.jumlah;qty.required=true;qty.className='fld';qtyLabel.append(qty);
    const unit=el('span',b.satuan),selected=el('small',pick.selectedOptions[0]?.textContent||b.nama);selected.dataset.selectedSource='';unit.dataset.unit='';pick.addEventListener('change',()=>{const bag=pick.value.startsWith('bj:');qty.step=bag?'1':'0.01';unit.textContent=bag?'karung':'kg';selected.textContent=pick.selectedOptions[0]?.textContent||pick.value;});
    row.append(label,selected,qtyLabel,unit);holder.append(row);
  });
  function fields(){return {kunci:key,pelanggan_id:Number(f.elements.pelanggan_id.value),barang:[...holder.querySelectorAll('[data-item]')].map(r=>({item_id:Number(r.dataset.item),pilih:r.querySelector('[name="pilih"]').value,jumlah:r.querySelector('[name="jumlah"]').value})),alasan:f.elements.alasan.value,sebab_selisih:f.elements.sebab_selisih.value,konfirmasi:f.elements.konfirmasi.checked};}
  function persist(){try{sessionStorage.setItem(space,JSON.stringify({data:fields(),uncertain,done}));}catch(_){}}
  function controls(){f.querySelectorAll('input,select,textarea,button').forEach(e=>e.disabled=busy||uncertain||done);save.disabled=busy||uncertain||done||!plan;status.disabled=busy;status.hidden=!uncertain;}
  async function call(url,method,body){if(window.SESIFORM&&!SESIFORM.periksa())throw Error('Sesi berubah. Periksa status dengan akun yang membuka formulir.');
    const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),20000);
    try{const r=await fetch(url,{method,credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':document.getElementById('formulir-sesi')?.dataset.token||''},body:body?JSON.stringify(body):undefined});
      if(r.status>=500)throw Error('Status server belum dapat dipastikan.');const j=await r.json();if(!r.ok){const err=Error(typeof j.detail==='string'?j.detail:'Pemeriksaan ditolak.');err.known=true;throw err;}return j;
    }finally{clearTimeout(timer);}}
  async function catalog(){const generation=++catalogVersion;try{const url=root.dataset.jasa==='1'?'/api/actions/barang-jasa?induk='+encodeURIComponent(f.elements.pelanggan_id.value):'/api/actions/barang-bisa-keluar';
    const choices=await call(url,'GET');if(generation!==catalogVersion)return;for(const select of holder.querySelectorAll('[name="pilih"]')){const value=select.value,label=select.selectedOptions[0]?.textContent||value;select.replaceChildren();option(select,value,label);for(const c of choices)if(c.value!==value)option(select,c.value,c.label);}
  }catch(e){message('Pilihan sumber belum dapat dimuat. Isian tetap tersedia; jangan menganggap sumber kosong.');}}
  f.elements.pelanggan_id.addEventListener('change',catalog);
  f.addEventListener('input',()=>{plan=null;save.hidden=true;area.replaceChildren(el('p','Isian berubah. Periksa dampak terbaru sebelum konfirmasi.'));persist();controls();});
  f.addEventListener('submit',async e=>{e.preventDefault();if(busy||uncertain||done||!f.reportValidity())return;
    busy=true;controls();plan=null;save.hidden=true;
    try{const p=await call(base+'/periksa','POST',fields());plan=p;const r=p.rencana;area.replaceChildren(el('h3','Seluruh kiriman: '+r.pemeriksaan.total_aktual_kg+' kg setelah koreksi'),el('p','Pelanggan: '+(r.sebelum.nama||'belum tercatat')+' → '+r.sesudah.nama));
      for(const b of r.barang)area.append(el('p','Item #'+b.item_id+' · '+b.nama_sebelum+(b.ganti_sumber?' → '+b.nama_sesudah:'')+': '+b.sebelum.berat_kg+' → '+b.sesudah.berat_kg+' kg'));
      for(const s of r.sumber){area.append(el('p',s.nama+': saldo sumber '+s.stok_kg+' → '+s.stok_sesudah_kg+' kg; bebas setelah reservasi '+s.bebas_kg+' → '+s.bebas_sesudah_kg+' kg; perubahan stok '+(-s.delta_kg)+' kg'));if(s.karung_sebelum!=null)area.append(el('p','Karung: '+s.karung_sebelum+' → '+s.karung_sesudah+'; karung bebas sebelum koreksi '+s.karung_bebas));}
      area.append(el('p',r.tiket?'Tiket '+r.tiket.kode+' · revisi '+(r.tiket.jumlah_revisi??'historis')+' · berat tiket '+r.pemeriksaan.berat_tiket_kg+' kg · selisih '+r.pemeriksaan.selisih_kg+' kg · ambang wajib sebab '+r.pemeriksaan.ambang_manual_kg+' kg':'Catatan asal tanpa tiket. Koreksi tidak membuat atau mengubah tiket TeraFlow.'));
      area.append(el('p','Alasan: '+r.alasan),el('p','Sebab selisih: '+(r.sebab_selisih||'Tidak diisi / tidak diwajibkan')),el('p','Verifikasi awal tetap tersimpan. Hanya pencatatan efektif pelanggan ini yang dikoreksi; pelanggan lain tidak berubah.'));
      save.hidden=false;message('Baca seluruh dampak, lalu konfirmasi penyimpanan.');
    }catch(err){message(err.message+' Isian tetap tersedia; periksa kembali data.');}finally{busy=false;controls();persist();}});
  save.addEventListener('click',async()=>{if(busy||uncertain||done||!plan)return;busy=true;controls();
    try{const result=await call(base+'/simpan','POST',{...fields(),dasar:plan.dasar});done=true;plan=null;save.hidden=true;message('Koreksi versi '+result.versi+' tersimpan. Buka riwayat untuk melihat hasil dan audit.');try{sessionStorage.removeItem(space);}catch(_){}}
    catch(err){plan=null;save.hidden=true;if(!err.known){uncertain=true;message('Status penyimpanan belum dapat dipastikan. Isian tetap tersedia; periksa status permintaan sebelum mengulang.');}else message(err.message+' Isian tetap tersedia. Baca data terbaru dan periksa dampak ulang; tidak ada pengiriman otomatis.');}
    finally{busy=false;controls();if(!done)persist();}});
  status.addEventListener('click',async()=>{if(busy)return;busy=true;controls();try{const r=await call(base+'/status?kunci='+encodeURIComponent(key),'GET');if(r.ditemukan){done=true;uncertain=false;message('Koreksi versi '+r.versi+' sudah tercatat. Buka riwayat; jangan ulangi pencatatan.');try{sessionStorage.removeItem(space);}catch(_){}}else{uncertain=false;plan=null;message('Belum ditemukan pencatatan untuk permintaan ini. Baca data terbaru dan periksa dampak kembali; identitas permintaan tetap sama.');}}catch(_){message('Status belum dapat dipastikan. Pertahankan isian dan periksa riwayat.');}finally{busy=false;controls();if(!done)persist();}});
  async function start(){try{const saved=JSON.parse(sessionStorage.getItem(space)||'null');if(saved?.data){const d=saved.data;key=d.kunci||key;if(![...f.elements.pelanggan_id.options].some(o=>o.value===String(d.pelanggan_id)))option(f.elements.pelanggan_id,d.pelanggan_id,'Pelanggan draf #'+d.pelanggan_id);f.elements.pelanggan_id.value=d.pelanggan_id;
      for(const b of d.barang||[]){const r=holder.querySelector('[data-item="'+b.item_id+'"]');if(!r)continue;const select=r.querySelector('[name="pilih"]');if(![...select.options].some(o=>o.value===b.pilih))option(select,b.pilih,'Sumber draf '+b.pilih);select.value=b.pilih;r.querySelector('[data-selected-source]').textContent=select.selectedOptions[0]?.textContent||b.pilih;const qty=r.querySelector('[name="jumlah"]');qty.value=b.jumlah;qty.step=b.pilih.startsWith('bj:')?'1':'0.01';r.querySelector('[data-unit]').textContent=b.pilih.startsWith('bj:')?'karung':'kg';}
      f.elements.alasan.value=d.alasan||'';f.elements.sebab_selisih.value=d.sebab_selisih||'';f.elements.konfirmasi.checked=false;uncertain=saved.uncertain===true;message('Draf dipulihkan. Baca data terbaru dan periksa dampak kembali.');}}
    catch(_){}controls();try{const selected=f.elements.pelanggan_id.value,choices=await call('/api/actions/pelanggan-kledo','GET');for(const c of choices)if(c.value!==selected)option(f.elements.pelanggan_id,c.value,c.label);else for(const o of f.elements.pelanggan_id.options)if(o.value===selected)o.textContent=c.label;}catch(_){message('Daftar pelanggan belum dapat dimuat; isian tetap tersedia.');}await catalog();}
  start();
})();
