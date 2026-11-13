(() => {
'use strict';const root=document.querySelector('#transfer-pk');if(!root)return;
const $=s=>root.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:2})+' kg';
const status={diminta:'Menunggu persetujuan Admin',disetujui:'Siap dipindahkan',dikirim:'Dipindahkan sebagian',selesai:'Selesai',ditolak:'Ditolak',gugur:'Tidak dilanjutkan',dalam_perjalanan:'Menunggu timbang',menunggu_admin:'Selisih · perlu Admin',dibatalkan:'Dibatalkan'};
let data, busy=false, decision, nonce=crypto.randomUUID().replaceAll('-','');
async function api(path,body){const r=await fetch('/api/transfer-bertahap'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','x-csrf-token':root.dataset.csrf}:{},body:body?JSON.stringify(body):undefined});let d;try{d=await r.json()}catch{throw Error('Balasan belum dapat dibaca. Perbarui status sebelum mengulang.')}if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Isian belum sah. Periksa jumlah dan pilihan.');return d}
function pesan(t,err=false){$('#pk-pesan').textContent=t;$('#pk-pesan').toggleAttribute('data-galat',err)}
function jumlahTransfer(r){return `<div class="tp-jumlah" data-sisa="${esc(r.sisa)}"><label>Cara mengisi jumlah<select class="fld" name="cara"><option value="karung">Karung bekas 50 kg dan curah</option><option value="kg">Langsung dalam kg</option></select></label><div data-unit="karung"><label>Jumlah karung bekas 50 kg<input class="fld" name="jumlah_karung" type="number" min="0" step="1" inputmode="numeric" value="${Math.floor(Math.round(Number(r.sisa)*100)/5000)}"></label><label>Curah / bagian karung (kg, boleh kosong)<input class="fld" name="berat_curah_kg" type="number" min="0" step="0.01" inputmode="decimal" value="${((Math.round(Number(r.sisa)*100)%5000)/100).toFixed(2)}"></label></div><label data-unit="kg" hidden>Jumlah dipindahkan (kg)<input class="fld" name="berat" type="number" min="0.01" step="0.01" max="${esc(r.sisa)}" inputmode="decimal"></label><p class="tp-meta" data-total role="status">Isi jumlah yang benar-benar dipindahkan. Sisa persetujuan ${fmt(r.sisa)}.</p></div>`}
function perbaruiJumlah(row){const box=row.querySelector('.tp-jumlah');if(!box)return;const active=!!row.querySelector('[name=pilih]')?.checked,mode=box.querySelector('[name=cara]').value;box.querySelector('[name=cara]').disabled=!active;box.querySelectorAll('[data-unit]').forEach(group=>{const enabled=active&&group.dataset.unit===mode;group.hidden=group.dataset.unit!==mode;group.querySelectorAll('input').forEach(x=>{x.disabled=!enabled;x.setCustomValidity('')})});const n=Number(box.querySelector('[name=jumlah_karung]').value||0),c=Number(box.querySelector('[name=berat_curah_kg]').value||0),kg=mode==='karung'?n*50+c:Number(box.querySelector('[name=berat]').value||0),cents=Math.round(kg*100),limit=Math.round(Number(box.dataset.sisa)*100);let error='';if(!Number.isFinite(kg)||kg<=0)error='Isi jumlah yang dipindahkan lebih dari nol.';else if(mode==='karung'&&(!Number.isInteger(n)||n<0||c<0))error='Isi karung dalam bilangan bulat dan curah nol atau lebih.';else if(cents>limit)error='Total melebihi sisa persetujuan '+fmt(box.dataset.sisa)+'.';row.dataset.totalCents=String(cents);if(active)box.querySelector(mode==='karung'?'[name=jumlah_karung]':'[name=berat]').setCustomValidity(error);box.querySelector('[data-total]').textContent=kg>0?'Total dipindahkan '+fmt(kg)+' · sisa persetujuan '+fmt(box.dataset.sisa)+(error?' · '+error:''):'Isi jumlah yang benar-benar dipindahkan. Sisa persetujuan '+fmt(box.dataset.sisa)+'.';box.querySelector('[data-total]').toggleAttribute('data-galat',active&&!!error)}
function muatan(row,mode){const item={permintaan_id:Number(row.dataset.id)};if(mode==='setujui')return {...item,berat_kg:row.querySelector('[name=berat]').value,tujuan:row.querySelector('[name=tujuan]').value};const cara=row.querySelector('[name=cara]').value;return cara==='karung'?{...item,cara,jumlah_karung:Number(row.querySelector('[name=jumlah_karung]').value||0),berat_curah_kg:row.querySelector('[name=berat_curah_kg]').value||'0'}:{...item,cara,berat_kg:row.querySelector('[name=berat]').value}}
function render(){const q=$('#pk-cari').value.toLowerCase();const matches=x=>JSON.stringify(x).toLowerCase().includes(q);
$('#pk-arahan').textContent=data.admin?'Pilih permintaan, periksa jumlah kg, lalu pilih Tumpukan atau silo PK di gudang tujuan dan setujui.':data.boleh_kirim?'Setelah barang dipindahkan, pilih lot yang disetujui, isi karung bekas 50 kg dan curah atau langsung kg, lalu tekan Catat transfer. Tujuan mengikuti persetujuan Admin.':'Permintaan Anda diperiksa Admin. Operator gudang asal mencatat transfer setelah barang dipindahkan; stok tujuan diperbarui otomatis.';
$('#pk-daftar').innerHTML=data.permintaan.filter(matches).map(r=>{const approve=data.admin&&r.status==='diminta', send=data.boleh_kirim&&['disetujui','dikirim'].includes(r.status)&&Number(r.sisa)>0;
return `<article class="tp-row" data-id="${r.id}" data-mode="${approve?'setujui':send?'kirim':''}"><label>${approve||send?`<input type="checkbox" name="pilih" aria-label="Pilih ${esc(r.lot)}">`:''}</label><div><h3>${esc(r.lot)}</h3><p>${esc(r.pemilik)} · ${esc(r.asal)}</p><p class="tp-meta">Diminta ${esc(r.peminta||'operator')}${r.waktu?' · '+esc(new Date(r.waktu).toLocaleString('id-ID')):''}</p><p class="tp-status">${esc(status[r.status]||r.status)}</p><p class="tp-meta">Diminta ${fmt(r.diminta)}${r.status==='diminta'?` · stok bebas ${fmt(r.bebas)}`:` · disetujui ${fmt(r.disetujui)}<br>${['selesai','gugur','ditolak'].includes(r.status)?'Sisa tidak dipindahkan':'Sisa belum dipindahkan'} ${fmt(r.sisa)}<br>${Number(r.perjalanan_kg)>0?'Dalam perjalanan lama '+fmt(r.perjalanan_kg)+' · ':''}Sudah dipindahkan ${fmt(r.selesai_kg)}`}</p>${r.sebab?`<p>${esc(r.sebab)}</p>`:''}${data.admin?`<p><button class="btn btn--kecil" type="button" data-koreksi="permintaan" data-id="${r.id}">Koreksi permintaan</button></p>`:''}</div>${approve?`<label>Setujui (kg)<input class="fld" name="berat" type="number" min="0.01" step="0.01" max="${r.bebas}" value="${Math.min(Number(r.diminta),Number(r.bebas))}"></label>`:send?jumlahTransfer(r):''}${approve?`<label>Tujuan<select class="fld" name="tujuan">${data.tujuan.map(t=>`<option value="${esc(t.nilai)}">${esc(t.nama)}</option>`).join('')}</select><button class="btn btn--kecil" type="button" data-action="tolak" data-id="${r.id}">Tolak dengan alasan</button></label>`:`<div>${esc(data.tujuan.find(t=>t.id===r.silo_id)?.nama||data.tujuan[0]?.nama||'Tumpukan')}${data.admin&&['disetujui','dikirim'].includes(r.status)?`<p><button class="btn btn--kecil" type="button" data-action="tutup-sisa" data-id="${r.id}">Tutup sisa persetujuan</button></p>`:''}</div>`}</article>`}).join('')||'<p>Tidak ada permintaan pada pencarian ini.</p>';
$('#pk-jalan').innerHTML=data.pengiriman.filter(matches).map(j=>`<article id="perjalanan-${j.id}"><h3>${j.pakai_kendaraan?'Perjalanan lama':'Transfer'} #${j.id}${j.pakai_kendaraan?' · '+esc(j.nomor_polisi):''}</h3><p>${j.pakai_kendaraan?esc(j.nama_sopir)+' · ':''}${esc(j.lintasan.asal.nama)} → ${esc(j.lintasan.tujuan.nama)}</p><p class="tp-status">${esc(j.status==='dalam_perjalanan'&&j.status_tiket==='SELESAI'?'Timbang selesai · menunggu pencatatan stok':status[j.status]||j.status)}</p><ul>${j.items.map(i=>`<li>${esc(i.lot)} · ${fmt(i.berat_kg)} ${i.transfer_id&&data.boleh_kirim?`<a href="/riwayat-transfer/${i.transfer_id}">Lihat rincian</a>`:''} ${data.admin&&!j.pakai_kendaraan&&j.status==='selesai'&&Number(i.berat_kg)>0?`<button class="btn btn--kecil" type="button" data-koreksi="transfer" data-id="${i.id}">Koreksi jumlah</button>`:''}</li>`).join('')}</ul><p>${j.pakai_kendaraan?'Muatan asal':'Total transfer efektif'} <strong>${fmt(j.total)}</strong>${j.bobot_timbang_kg!==null?` · hasil timbang ${fmt(j.bobot_timbang_kg)} · selisih ${fmt(j.selisih_kg)}`:''}</p>${j.alasan?`<p>${esc(j.alasan)}</p>`:''}<div class="tp-actions">${j.pakai_kendaraan&&root.dataset.tera&&(j.tiket_id||j.status==='dalam_perjalanan')?`<a class="btn" href="${esc(root.dataset.tera)}/timbangan/${j.tiket_id?'transaksi/'+j.tiket_id:'timbang/TRANSFER?pengiriman_pk_id='+j.id}">${j.tiket_id?'Lihat tiket timbang':'Buka timbang perjalanan'}</a>`:''}${data.admin&&j.status==='menunggu_admin'?`<button class="btn" data-action="terima-selisih" data-id="${j.id}">Periksa & terima selisih</button>`:''}${data.admin&&j.status==='dalam_perjalanan'&&!j.tiket_id?`<button class="btn" data-action="batal" data-id="${j.id}">Batalkan perjalanan</button>`:''}</div></article>`).join('')||'<p>Belum ada transfer pada pencarian ini.</p>';if(data.admin&&data.koreksi?.length)$('#pk-jalan').insertAdjacentHTML('beforeend',`<details><summary>Riwayat koreksi Admin</summary><ul>${data.koreksi.map(k=>`<li>Koreksi #${k.id} · ${esc(new Date(k.waktu).toLocaleString('id-ID'))} · ${esc(k.alasan)}${k.ringkasan?.length?`<ul>${k.ringkasan.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}</li>`).join('')}</ul></details>`);selected();}
function selected(){const rows=[...root.querySelectorAll('[name=pilih]:checked')].map(x=>x.closest('article')),mode=rows[0]?.dataset.mode;root.querySelectorAll('#pk-daftar article').forEach(r=>{r.querySelectorAll('[name=berat],[name=tujuan]').forEach(x=>x.disabled=!r.querySelector('[name=pilih]')?.checked);perbaruiJumlah(r)});$('#pk-simpan').hidden=!rows.length;$('#pk-simpan').textContent=mode==='setujui'?`Setujui ${rows.length} permintaan dipilih`:`Catat transfer · ${rows.length} lot`;return {rows,mode}}
async function load(){if(busy)return;busy=true;try{data=await api('');render();pesan('Status diperbarui.')}catch(e){pesan(e.message,true)}finally{busy=false}}
$('#pk-pilihan').addEventListener('change',e=>{if(e.target.name==='cara'){const row=e.target.closest('article'),cents=Number(row.dataset.totalCents||0);if(e.target.value==='kg')row.querySelector('[name=berat]').value=cents>0?(cents/100).toFixed(2):'';else{row.querySelector('[name=jumlah_karung]').value=cents>0?Math.floor(cents/5000):'';row.querySelector('[name=berat_curah_kg]').value=cents>0?((cents%5000)/100).toFixed(2):''}perbaruiJumlah(row);return}if(e.target.name!=='pilih')return;if(e.target.checked){const mode=e.target.closest('article').dataset.mode;root.querySelectorAll('[name=pilih]:checked').forEach(x=>{if(x.closest('article').dataset.mode!==mode)x.checked=false})}selected()});
$('#pk-pilihan').addEventListener('input',e=>{const row=e.target.closest('article');if(row&&e.target.tagName==='INPUT')perbaruiJumlah(row)});
$('#pk-pilihan').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;const {rows,mode}=selected();if(!rows.length)return;const items=rows.map(r=>muatan(r,mode));busy=true;$('#pk-simpan').disabled=true;try{const result=await api(mode==='setujui'?'/setujui':'/pengiriman',mode==='setujui'?{items}:{items,kunci:nonce});nonce=crypto.randomUUID().replaceAll('-','');busy=false;await load();pesan(mode==='setujui'?'Permintaan dipilih telah disetujui.':`Transfer #${result.id} tercatat. Stok asal dan tujuan sudah diperbarui.`);if(result.id)document.getElementById('perjalanan-'+result.id)?.scrollIntoView({behavior:'smooth',block:'center'})}catch(err){pesan(err.message+' Isian tetap tersedia. Jika sambungan terputus, ulangi tanpa mengubah muatan atau perbarui status dahulu.',true)}finally{busy=false;$('#pk-simpan').disabled=false}});
root.addEventListener('click',e=>{if(e.target.matches('[data-tutup]'))e.target.closest('dialog').close();const b=e.target.closest('[data-action]');if(!b)return;decision={id:Number(b.dataset.id),action:b.dataset.action};$('#pk-alasan-judul').textContent=b.textContent;$('#pk-alasan-keterangan').textContent=decision.action==='tutup-sisa'?'Persetujuan asli tetap tersimpan. Hanya sisa yang belum berangkat dilepas; tidak dapat ditutup selama ada perjalanan belum selesai.':decision.action==='terima-selisih'?'Periksa hasil timbang dan muatan lot di perjalanan. Menerima selisih mempertahankan bobot lot asal dan mencatat stok tujuan.':'Keputusan hanya berlaku pada baris ini. Perjalanan yang sudah memiliki tiket tidak dapat dibatalkan dari sini.';$('#pk-alasan-form').reset();$('#pk-alasan').showModal()});
$('#pk-alasan-form').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;const button=e.submitter;button.disabled=true;try{await api(['tolak','tutup-sisa'].includes(decision.action)?`/permintaan/${decision.id}/${decision.action}`:`/${decision.id}/${decision.action}`,{alasan:new FormData(e.target).get('alasan')});$('#pk-alasan').close();busy=false;await load();pesan('Keputusan tersimpan.')}catch(err){pesan(err.message,true)}finally{busy=false;button.disabled=false}});
// Koreksi dibuka dari catatan yang sama; hanya angka yang diperiksa dapat disimpan.
let koreksiAktif=null, koreksiDiperiksa=null;
const formKoreksi=$('#pk-koreksi-form');
function bersihkanDampak(){
  koreksiDiperiksa=null;
  $('#pk-koreksi-dampak').hidden=true;
  $('#pk-koreksi-konfirmasi').hidden=true;
  formKoreksi.elements.konfirmasi.checked=false;
  formKoreksi.querySelector('[value=simpan]').disabled=true;
}
function aturKoreksi(){
  const aksi=formKoreksi.elements.aksi.value;
  const jumlah=['minta','persetujuan','jumlah','bahan'].includes(aksi);
  $('#pk-koreksi-berat').hidden=!jumlah;
  formKoreksi.elements.berat_kg.disabled=!jumlah;
  formKoreksi.elements.berat_kg.required=jumlah;
  formKoreksi.elements.berat_kg.min=aksi==='jumlah'?'0':'0.01';
  const tujuan=koreksiAktif.jenis==='permintaan'&&aksi==='persetujuan'&&Number(koreksiAktif.row.selesai_kg)===0;
  $('#pk-koreksi-tujuan').hidden=!tujuan;
  formKoreksi.elements.tujuan.disabled=!tujuan;
  const pindah=koreksiAktif.jenis==='transfer'&&koreksiAktif.row.pemindahan?.length>0&&(aksi==='bahan'||Number(formKoreksi.elements.berat_kg.value)>Number(koreksiAktif.row.berat_kg));
  $('#pk-koreksi-pindah').hidden=!pindah;
  formKoreksi.elements.pemindahan_id.disabled=!pindah;
  formKoreksi.elements.pemindahan_id.required=aksi==='bahan';
}
root.addEventListener('click',e=>{
  const b=e.target.closest('[data-koreksi]');
  if(!b||!data.admin||busy)return;
  const jenis=b.dataset.koreksi,id=Number(b.dataset.id);
  const row=jenis==='permintaan'?data.permintaan.find(r=>r.id===id):data.pengiriman.flatMap(j=>j.items).find(i=>i.id===id);
  if(!row)return;
  koreksiAktif={jenis,id,row,kunci:crypto.randomUUID().replaceAll('-','')};
  formKoreksi.reset();bersihkanDampak();$('#pk-koreksi-pesan').textContent='';
  $('#pk-koreksi-judul').textContent=jenis==='transfer'?'Koreksi jumlah transfer':'Koreksi permintaan';
  $('#pk-koreksi-lot').textContent=row.lot+(jenis==='transfer'?' · saat ini '+fmt(row.berat_kg):' · '+(status[row.status]||row.status));
  let pilihan;
  if(jenis==='transfer')pilihan=[['jumlah','Jumlah transfer (0 kg = batal)'],...(row.pemindahan?.length?[['bahan','Bahan dari tumpukan']]:[])];
  else if(row.status==='diminta')pilihan=[['minta','Betulkan jumlah yang diminta'],['batal','Batalkan permintaan']];
  else if(['disetujui','dikirim'].includes(row.status))pilihan=[['persetujuan','Betulkan persetujuan'],...(Number(row.selesai_kg)===0?[['kembali','Kembalikan ke sebelum persetujuan'],['batal','Batalkan permintaan']]:[])];
  else pilihan=Number(row.disetujui)>0?[['persetujuan','Betulkan persetujuan'],['buka','Buka kembali sisa persetujuan']]:[];
  if(!pilihan.length){pesan('Permintaan sudah tidak aktif. Buat permintaan baru dari lot yang benar.',true);return}
  formKoreksi.elements.aksi.innerHTML=pilihan.map(([v,t])=>`<option value="${v}">${esc(t)}</option>`).join('');
  formKoreksi.elements.berat_kg.value=jenis==='transfer'?row.berat_kg:row.status==='diminta'?row.diminta:row.disetujui;
  formKoreksi.elements.tujuan.innerHTML=data.tujuan.map(t=>`<option value="${esc(t.nilai)}" ${t.id===row.silo_id||!row.silo_id&&t.nilai==='ditumpuk'?'selected':''}>${esc(t.nama)}</option>`).join('');
  formKoreksi.elements.pemindahan_id.innerHTML='<option value="">Tetap sebagai stok tumpukan</option>'+(row.pemindahan||[]).map(m=>`<option value="${m.id}">Pemindahan #${m.id} · ${esc(m.nama)} · ${fmt(m.berat_kg)}</option>`).join('');
  aturKoreksi();$('#pk-koreksi').showModal();
});
formKoreksi.addEventListener('input',e=>{
  if(e.target.name==='konfirmasi'){
    formKoreksi.querySelector('[value=simpan]').disabled=!koreksiDiperiksa||!e.target.checked;
    return;
  }
  bersihkanDampak();aturKoreksi();
});
formKoreksi.addEventListener('change',e=>{
  if(e.target.name!=='konfirmasi'){
    if(e.target.name==='aksi'){
      if(e.target.value==='bahan'){
        const m=koreksiAktif.row.pemindahan[0];
        formKoreksi.elements.pemindahan_id.value=String(m.id);formKoreksi.elements.berat_kg.value=m.berat_kg;
      }else if(koreksiAktif.jenis==='transfer')formKoreksi.elements.berat_kg.value=koreksiAktif.row.berat_kg;
    }
    if(e.target.name==='pemindahan_id'&&formKoreksi.elements.aksi.value==='bahan'){
      const m=koreksiAktif.row.pemindahan.find(m=>String(m.id)===e.target.value);if(m)formKoreksi.elements.berat_kg.value=m.berat_kg;
    }
    bersihkanDampak();aturKoreksi()
  }
});
function tampilkanDampak(p){
  const jumlah=x=>x===null||x===undefined?'Belum diisi':fmt(x);
  const baris=(judul,a,b)=>`<tr><td>${esc(judul)}</td><td>${jumlah(a)}</td><td>${jumlah(b)}</td></tr>`;
  let rows='';
  for(const x of p.permintaan){
    if(koreksiAktif.jenis==='permintaan'){
      rows+=baris('Diminta',x.before.berat_minta_kg,x.after.berat_minta_kg);
      rows+=baris('Disetujui',x.before.berat_setuju_kg,x.after.berat_setuju_kg);
    }
    rows+=baris('Total transfer permintaan',x.before.berat_kirim_kg,x.after.berat_kirim_kg);
  }
  for(const x of p.items)rows+=baris('Transfer ini',x.before.berat_kg,x.after.berat_kg);
  if(p.stok_asal_before!==undefined)rows+=baris('Stok fisik gudang asal (seluruh lot)',p.stok_asal_before,p.stok_asal_after);
  if(p.dicadangkan_sebelum!==undefined)rows+=baris('Cadangan permintaan ini',p.dicadangkan_sebelum,p.dicadangkan_sesudah);
  rows+=baris('Stok bebas pemilik ini di gudang asal',p.stok_bebas_sebelum,p.stok_bebas_sesudah);

  if(p.tumpukan_before!==null&&p.tumpukan_before!==undefined)rows+=baris('Sisa tumpukan transfer ini',p.tumpukan_before,p.tumpukan_after);
  for(const x of p.pk_chain?.moves||[])rows+=baris('Pemindahan tumpukan ke silo #'+x.id,x.effective_before,x.effective_after);
  for(const x of p.pk_chain?.usages||[])if(x.before.berat_akhir_kg!==null)rows+=baris('Sisa silo · '+x.kode,x.before.berat_akhir_kg,x.after.berat_akhir_kg);
  let html=`<h3>Dampak sebelum disimpan</h3><p>${esc(p.penjelasan)}</p><div class="tp-tabel"><table><thead><tr><th>Catatan</th><th>Sebelum</th><th>Sesudah</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  for(const pr of p.pk_chain?.processes||[]){
    const href=pr.status==='selesai'?'/riwayat-sosoh/'+pr.id:'/proses-aktif/sosoh/'+encodeURIComponent(pr.kode);
    html+=`<h3><a href="${href}" target="_blank" rel="noopener">${esc(pr.kode)}</a> · ${esc(pr.status)}</h3><div class="tp-tabel"><table><thead><tr><th>Catatan</th><th>Sebelum</th><th>Sesudah</th></tr></thead><tbody>${baris('Bahan proses',pr.bahan_before,pr.bahan_after)}${baris('Hasil timbang (tetap)',pr.hasil_tercatat,pr.hasil_tercatat)}${baris('Susut',pr.susut_before,pr.susut_after)}</tbody></table></div>`;
  }
  for(const warning of p.pk_chain?.warnings||[])html+=`<p class="tp-galat">${esc(warning)} Proses belum boleh diselesaikan sebelum bahan/hasil sesuai.</p>`;
  if(koreksiAktif.jenis==='permintaan')html+=`<p>Status sesudah koreksi: <strong>${esc(status[p.permintaan[0].after.status]||p.permintaan[0].after.status)}</strong>. Perubahan persetujuan mengubah cadangan stok; tidak memindahkan barang.</p>`;
  $('#pk-koreksi-dampak').innerHTML=html;
  $('#pk-koreksi-dampak').hidden=false;
  $('#pk-koreksi-konfirmasi').hidden=false;
}
formKoreksi.addEventListener('submit',async e=>{
  e.preventDefault();if(busy||!koreksiAktif)return;
  const tahap=e.submitter.value;
  let body=koreksiDiperiksa;
  if(tahap==='simpan'&&(!body||!formKoreksi.elements.konfirmasi.checked))return;
  if(tahap==='periksa'){
    const f=new FormData(formKoreksi);
    body={aksi:f.get('aksi'),berat_kg:f.get('berat_kg'),tujuan:f.get('tujuan'),pemindahan_id:f.get('pemindahan_id')?Number(f.get('pemindahan_id')):null,alasan:f.get('alasan'),kunci:koreksiAktif.kunci};
  }else body={...body,konfirmasi:true};
  busy=true;const button=e.submitter;button.disabled=true;$('#pk-koreksi-pesan').textContent='';$('#pk-koreksi-pesan').removeAttribute('data-galat');
  try{
    const result=await api(`/koreksi/${koreksiAktif.jenis}/${koreksiAktif.id}/${tahap}`,body);
    if(tahap==='periksa'){
      koreksiDiperiksa={...body,pemeriksaan:result.pemeriksaan};tampilkanDampak(result.rancangan);
      $('#pk-koreksi-pesan').textContent='Belum ada perubahan disimpan. Periksa dampak lalu centang konfirmasi.';
    }else{
      $('#pk-koreksi').close();busy=false;await load();pesan(`Koreksi #${result.peristiwa_id} tersimpan. Stok dan bahan proses terkait sudah diperbarui.`);
    }
  }catch(err){$('#pk-koreksi-pesan').textContent=err.message+' Isian tetap tersedia.';$('#pk-koreksi-pesan').setAttribute('data-galat','')}
  finally{busy=false;button.disabled=tahap==='simpan'&&!formKoreksi.elements.konfirmasi.checked}
});

$('#pk-panduan-buka').onclick=()=>$('#pk-panduan').showModal();$('#pk-muat').onclick=load;$('#pk-cari').oninput=()=>data&&render();load();
})();
