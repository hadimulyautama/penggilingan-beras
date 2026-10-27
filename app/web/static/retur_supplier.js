/* Pengajuan saja. Tidak ada endpoint muat, verifikasi, atau mutasi stok. */
(function(){
 'use strict';
 const root=document.querySelector('[data-rsp-form-root],[data-rsp-detail]');
 if(!root||root.dataset.rspSiap)return;root.dataset.rspSiap='1';
 const pesan=root.querySelector('[data-rsp-pesan]');
 const csrf=root.querySelector('[name="_csrf"]')?.value||'';
 const rup=new Intl.NumberFormat('id-ID',{maximumFractionDigits:2});
 const kg=n=>n===null||n===undefined?'Belum tersedia':rup.format(Number(n))+' kg';
 const angka=v=>{const n=Number(String(v).replace(',','.'));return String(v).trim()&&Number.isFinite(n)?n:null;};
 let sibuk=false;const keadaan=new Map();
 function kunci(on){sibuk=on;root.setAttribute('aria-busy',String(on));
  root.querySelectorAll('button,input,textarea,select').forEach(el=>{if(on){keadaan.set(el,el.disabled);el.disabled=true;}else if(keadaan.has(el)){el.disabled=keadaan.get(el);keadaan.delete(el);}});
 }
 function info(text){pesan.textContent=text;pesan.hidden=!text;if(text)pesan.scrollIntoView({block:'nearest'});}
 async function kirim(url,data){
  const r=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)});
  let body;try{body=await r.json();}catch(_){throw new Error('Jawaban server belum dapat dipastikan. Periksa status atau riwayat sebelum mengulang.');}
  return {r,body};
 }
 function gagal(body){return typeof body.detail==='string'?body.detail:'Isian belum diterima. Periksa kembali jumlah, alasan, dan izin akun.';}
 function teks(tag,value,parent){const el=document.createElement(tag);el.textContent=value;parent.append(el);return el;}
 // Tindakan pada pengajuan tersimpan. Halaman tidak mengirim POST saat dibuka.
 root.querySelectorAll('[data-rsp-tindakan]').forEach(form=>form.addEventListener('submit',async e=>{
  e.preventDefault();if(sibuk)return;
  const data=form.elements.tiket_id?{tiket_id:Number(form.elements.tiket_id.value)}:{alasan:form.elements.alasan.value};
  if(form.elements.tiket_id&&!form.elements.tiket_id.value){info('Pilih tiket Retur ke Supplier terlebih dahulu.');return;}
  if('alasan' in data&&!data.alasan.trim()){info('Alasan pembatalan wajib diisi.');return;}
  kunci(true);info('');
  try{const {r,body}=await kirim(form.action,data);
   if(!r.ok){info(gagal(body));if(body.tidak_pasti||r.status>=500)teks('a','Periksa status pengajuan terbaru',pesan).href=location.pathname;return;}
   if(body.ok&&typeof body.alamat==='string'&&body.alamat.startsWith('/retur-supplier/'))location.assign(body.alamat);
   else throw new Error('Status tindakan belum dapat dipastikan. Periksa pengajuan terbaru sebelum mengulang.');
  }catch(err){info(err.message||'Status tindakan belum dapat dipastikan.');teks('a','Periksa status pengajuan terbaru',pesan).href=location.pathname;}
  finally{kunci(false);}
 }));
 const form=root.querySelector('[data-rsp-isian]');if(!form)return;
 const prefix='/barang-masuk/'+root.dataset.tid+'/retur-supplier';
 const ruang='rsp:v1:'+root.dataset.actor+':'+root.dataset.tid;
 let opsi=JSON.parse(root.querySelector('[data-rsp-data]').textContent),key=root.dataset.key,dasar='',tidakPasti=false;
 const status=root.querySelector('[data-rsp-status]');
 function baris(){return [...root.querySelectorAll('[data-rsp-item]')];}
 function kontrol(k){return baris().find(el=>el.dataset.rspItem===k);}
 function payload(){return {jumlah:baris().filter(el=>el.querySelector('[name="pilih"]').checked).map(el=>({kunci:el.dataset.rspItem,jumlah:el.querySelector('[data-rsp-qty]').value})),alasan:form.elements.alasan.value,catatan:form.elements.catatan.value};}
 function simpanDraf(){try{sessionStorage.setItem(ruang,JSON.stringify({...payload(),key,tidakPasti}));}catch(_){/* Draf tetap ada di formulir bila penyimpanan perangkat tidak tersedia. */}}
 function tahap(n){root.querySelectorAll('[data-rsp-stage]').forEach(el=>el.hidden=el.dataset.rspStage!==String(n));root.querySelectorAll('.rsp-tahap li').forEach((el,i)=>{if(i===n-1)el.setAttribute('aria-current','step');else el.removeAttribute('aria-current');});root.querySelector('[data-rsp-stage="'+n+'"] h2')?.focus();}
 function hitung(){
  let bags=0,bulk=0,total=0,pilih=0,belum=false;
  for(const el of baris()){
   const o=opsi.find(x=>x.kunci===el.dataset.rspItem),check=el.querySelector('[name="pilih"]'),qty=el.querySelector('[data-rsp-qty]');if(!o)continue;
   qty.disabled=!check.checked||check.disabled;
   const n=angka(qty.value),ratio=angka(o.per_kg),valid=n!==null&&n>0&&ratio!==null;
   const weight=valid?n*ratio:null;
   el.querySelector('[data-rsp-weight]').textContent=check.checked?kg(weight):'Belum dipilih';
   el.querySelector('[data-rsp-sisa]').textContent=check.checked&&valid?kg(o.tersedia_kg!==null&&o.tersedia_kg!==undefined?Number(o.tersedia_kg)-weight:null):'Belum diisi';
   if(check.checked){pilih++;if(!valid)belum=true;else{total+=weight;if(o.satuan==='karung')bags+=n;else bulk+=weight;}}
  }
  const box=root.querySelector('[data-rsp-total]');box.replaceChildren();
  teks('p','Barang dipilih: '+pilih+' partai',box);teks('p','Jumlah karung: '+rup.format(bags)+' karung',box);teks('p','Berat curah: '+kg(bulk),box);teks('strong','Total pengajuan: '+(belum?'Belum lengkap':kg(total)),box);
 }
 function saldoBaru(data){
  if(!Array.isArray(data))return;
  for(const o of data){const el=kontrol(o.kunci);if(!el)continue;
   opsi=opsi.map(x=>x.kunci===o.kunci?o:x);
   el.querySelector('[data-rsp-max]').textContent=o.maksimum+' '+o.satuan;
   el.querySelector('[data-rsp-physical]').textContent=kg(o.stok_kg);el.querySelector('[data-rsp-reserved]').textContent=kg(o.terikat_kg);
   // Pilihan dan jumlah operator tidak dibuang walaupun stok menjadi nol.
   // Pemeriksaan ulang yang berikut menentukan apakah masih dapat disimpan.
  }hitung();
 }
 root.querySelector('[data-rsp-mulai]')?.addEventListener('click',()=>{info('');tahap(2);});
 root.querySelectorAll('[data-rsp-back]').forEach(el=>el.addEventListener('click',()=>{if(!sibuk){tahap(Number(el.dataset.rspBack));info('');}}));
 form.addEventListener('input',()=>{dasar='';hitung();simpanDraf();});
 form.addEventListener('change',()=>{dasar='';hitung();simpanDraf();});
 form.addEventListener('submit',async e=>{
  e.preventDefault();if(sibuk)return;
  if(tidakPasti){info('Periksa status pengajuan sebelumnya sebelum mengirim ulang.');status.hidden=false;return;}
  const data=payload();simpanDraf();kunci(true);info('');
  try{const {r,body}=await kirim(prefix+'/periksa',data);
   if(!r.ok){info(gagal(body));saldoBaru(body.opsi);return;}
   dasar=body.dasar;
   const review=root.querySelector('[data-rsp-review]');review.replaceChildren();
   body.items.forEach(x=>{const a=teks('article','',review);a.className='rsp-item';teks('h3',x.nama+' · '+x.kode,a);teks('p',x.pemilik+' · '+x.lokasi,a);teks('p',x.jumlah+' '+x.satuan+' · '+kg(x.bobot_kg),a);teks('p','Sisa tersedia setelah dialokasikan: '+kg(x.proyeksi_sisa_kg),a);});
   teks('p','Total karung: '+body.total_karung+' karung · Total curah: '+kg(body.total_curah_kg),review);teks('strong','Total pengajuan: '+kg(body.total_kg),review);
   root.querySelector('[data-rsp-reason]').textContent=body.alasan;root.querySelector('[data-rsp-note]').textContent=body.catatan||'';tahap(3);
  }catch(_){info('Pemeriksaan belum dapat dimuat. Isian tetap tersedia; coba periksa kembali setelah sambungan pulih.');}
  finally{kunci(false);}
 });
 root.querySelector('[data-rsp-save]').addEventListener('click',async()=>{
  if(sibuk)return;
  if(!dasar||tidakPasti){tahap(2);info('Periksa ulang pengajuan dan status sebelumnya terlebih dahulu.');return;}
  const data={...payload(),kunci:key,dasar};let berhasil=false;simpanDraf();kunci(true);info('');
  try{const {r,body}=await kirim(prefix+'/simpan',data);
   if(!r.ok){if(body.tidak_pasti||r.status>=500){tidakPasti=true;status.hidden=false;info('Status penyimpanan belum dapat dipastikan. Periksa status pengajuan sebelum mengulang. '+gagal(body));}else{tahap(2);dasar='';info(gagal(body));saldoBaru(body.opsi);}return;}
   if(!body.ok||typeof body.alamat!=='string'||!body.alamat.startsWith('/retur-supplier/'))throw new Error('Status belum pasti');
   berhasil=true;try{sessionStorage.removeItem(ruang);}catch(_){}location.assign(body.alamat);
  }catch(_){tidakPasti=true;status.hidden=false;info('Status penyimpanan belum dapat dipastikan. Isian dipertahankan. Periksa status pengajuan atau daftar Pengajuan sebelum mengulang.');}
  finally{kunci(false);if(!berhasil)simpanDraf();}
 });
 status.addEventListener('click',async()=>{
  if(sibuk)return;let ditemukan=false;kunci(true);
  try{const r=await fetch(prefix+'/status?kunci='+encodeURIComponent(key),{headers:{Accept:'application/json'},credentials:'same-origin',cache:'no-store'});const data=await r.json();
   if(!r.ok)throw new Error('Status belum terbaca');
   if(data.ditemukan&&data.alamat){ditemukan=true;try{sessionStorage.removeItem(ruang);}catch(_){}location.assign(data.alamat);return;}
   tidakPasti=false;dasar='';status.hidden=true;tahap(2);info('Belum ada pengajuan yang terbaca untuk kiriman ini. Baca saldo terbaru dan periksa ulang sebelum menyimpan. Kunci kiriman yang sama tetap dipakai untuk mencegah duplikasi.');
  }catch(_){info('Status pengajuan masih belum dapat dipastikan. Periksa daftar pengajuan atau riwayat sebelum mengulang.');}
  finally{kunci(false);if(!ditemukan)simpanDraf();}
 });
 try{const saved=JSON.parse(sessionStorage.getItem(ruang));
  if(saved&&Array.isArray(saved.jumlah)&&typeof saved.key==='string'&&/^[A-Za-z0-9_-]{16,64}$/.test(saved.key)){
   key=saved.key;tidakPasti=!!saved.tidakPasti;
   for(const x of saved.jumlah){const el=kontrol(x.kunci);if(el){el.querySelector('[name="pilih"]').checked=true;el.querySelector('[data-rsp-qty]').value=typeof x.jumlah==='string'?x.jumlah:'';}}
   form.elements.alasan.value=typeof saved.alasan==='string'?saved.alasan:'';form.elements.catatan.value=typeof saved.catatan==='string'?saved.catatan:'';
   tahap(2);info('Isian sebelumnya dipulihkan. Periksa saldo terbaru sebelum melanjutkan.');status.hidden=!tidakPasti;
  }
 }catch(_){}hitung();
})();
