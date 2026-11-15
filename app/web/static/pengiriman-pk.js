(() => {
'use strict';
const root=document.querySelector('#transfer-pk');if(!root)return;
const $=s=>root.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:2})+' kg';
const waktu=s=>s?new Date(s).toLocaleString('id-ID',{dateStyle:'medium',timeStyle:'short'}):'Belum tercatat';
const status={perlu_transfer:'Siap / sebagian',diminta:'Menunggu Admin',disetujui:'Siap dipindahkan',siap:'Siap dipindahkan',sebagian:'Dipindahkan sebagian',dikirim:'Dipindahkan sebagian',selesai:'Selesai',ditutup:'Sisa ditutup',ditolak:'Ditolak',gugur:'Tidak dilanjutkan',dalam_perjalanan:'Menunggu timbang',menunggu_admin:'Selisih · perlu Admin',dibatalkan:'Dibatalkan'};
let data,busy=false,decision,formAktif=null,pendingPayload=null;
const pilihan=new Set(),qawal=new URLSearchParams(location.search);
let tab=qawal.get('tab')==='riwayat'||qawal.has('pengiriman')||location.hash.startsWith('#perjalanan-')?'riwayat':'permintaan';
const filters={permintaan:{status:'',asal:'',tujuan:''},riwayat:{status:'',asal:'',tujuan:''}};
for(const k of ['status','asal','tujuan'])if(qawal.has(k))filters[tab][k]=qawal.get(k);
$('#pk-cari').value=(qawal.get('cari')||'').slice(0,200);
async function api(path,body){
 const r=await fetch('/api/transfer-bertahap'+path,{method:body?'POST':'GET',cache:'no-store',headers:body?{'Content-Type':'application/json','x-csrf-token':root.dataset.csrf}:{},body:body?JSON.stringify(body):undefined});
 let d;try{d=await r.json()}catch{throw Error('Balasan belum dapat dibaca. Ulangi pencatatan dengan isian yang sama.')}
 if(!r.ok){const e=Error(typeof d.detail==='string'?d.detail:'Isian belum sah. Periksa jumlah dan pilihan.');e.pasti=r.status>=400&&r.status<500;throw e}return d;
}
function pesan(t,err=false){$('#pk-pesan').textContent=t;$('#pk-pesan').toggleAttribute('data-galat',err)}
function fase(r){if(r.status==='disetujui')return Number(r.selesai_kg)>0?'sebagian':'siap';if(r.status==='dikirim')return 'sebagian';if(['selesai','gugur'].includes(r.status)&&Number(r.disetujui)>0&&Number(r.sisa)>0)return 'ditutup';return r.status}
function mode(r){return data.admin&&r.status==='diminta'?'setujui':data.boleh_kirim&&['disetujui','dikirim'].includes(r.status)&&Number(r.sisa)>0?'kirim':''}
function tujuan(r){return (r.tujuan_nama||data.tujuan.find(t=>t.id===r.silo_id)?.nama||(!r.silo_id?'Tumpukan':'Silo tidak tersedia'))+' · '+data.gudang_tujuan.nama}
function badge(k){return `<span class="tp-badge tp-badge--${esc(k)}">${esc(status[k]||k)}</span>`}
function urlSimpan(){
 const q=new URLSearchParams();q.set('tab',tab);q.set('status',filters[tab].status||'');
 for(const [k,v] of Object.entries(filters[tab]))if(v)q.set(k,v);
 if($('#pk-cari').value.trim())q.set('cari',$('#pk-cari').value.trim());
 history.replaceState(history.state,'','/transfer-bertahap?'+q);
}
function cocok(r,riwayat=false){
 const f=filters[tab],q=$('#pk-cari').value.trim().toLocaleLowerCase('id-ID');
 const asal=riwayat?r.lintasan.asal.gudang_id:r.asal_id;
 const target=riwayat?r.lintasan.tujuan.silo_id:r.silo_id;
 const text=riwayat?[`Transfer #${r.id}`,r.nomor_polisi,r.nama_sopir,r.lintasan.asal.nama,r.lintasan.tujuan.nama,...r.items.flatMap(i=>[i.lot,data.permintaan.find(x=>x.id===i.permintaan_id)?.pemilik])]:[r.lot,r.pemilik,r.peminta,r.asal,tujuan(r),`Permintaan #${r.id}`];
 const statusCocok=!f.status||(!riwayat&&f.status==='perlu_transfer'?['siap','sebagian'].includes(fase(r)):(riwayat?r.status:fase(r))===f.status);
 return (!q||text.join(' ').toLocaleLowerCase('id-ID').includes(q))&&statusCocok&&(!f.asal||String(asal)===f.asal)&&(!f.tujuan||(target?String(target):'ditumpuk')===f.tujuan);
}
function kosong(nama){return `<div class="tp-kosong"><h3>Tidak ada ${nama} yang sesuai</h3><p>Periksa pencarian atau tampilkan semua status.</p><button class="btn" type="button" data-semua>Tampilkan semua</button></div>`}
function render(){
 if(!data)return;pilihan.clear();
 root.querySelectorAll('[data-pk-tab]').forEach(a=>{if(a.dataset.pkTab===tab)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
 $('#pk-permintaan').hidden=tab!=='permintaan';$('#pk-perjalanan').hidden=tab!=='riwayat';
 $('#pk-jumlah-permintaan').textContent=data.permintaan.length;$('#pk-jumlah-riwayat').textContent=data.pengiriman.length;
 $('#pk-arahan').textContent=tab==='riwayat'?'Buka detail untuk memeriksa transfer dan jejak koreksi.':data.admin?'Periksa permintaan, pilih jumlah dan tujuan, lalu setujui. Persetujuan belum memindahkan stok.':data.boleh_kirim?'Setelah barang dipindahkan, catat jumlah aktual. Gunakan karung bekas 50 kg dan curah, atau langsung kg.':'Permintaan dimulai dari detail bahan baku → Minta lot ini. Pantau persetujuan dan pencatatannya di sini.';
 const rs=data.permintaan.filter(r=>cocok(r)),js=data.pengiriman.filter(r=>cocok(r,true));
 $('#pk-daftar').innerHTML=rs.map(r=>`<article class="tp-row" data-id="${r.id}">
 <div class="tp-pilih">${mode(r)?`<label class="tp-pilih"><input type="checkbox" name="pilih" value="${r.id}" aria-label="Pilih ${esc(r.lot)} · permintaan ${r.id}"></label>`:''}</div>
 <div class="tp-lot"><h3>${esc(r.lot)}</h3><p>${esc(r.pemilik)}</p><p class="tp-meta">Permintaan #${r.id} · ${esc(r.peminta)}<br>${esc(waktu(r.waktu))}</p>${badge(fase(r))}</div>
 <div class="tp-angka"><p>Diminta <strong>${fmt(r.diminta)}</strong></p>${r.status==='diminta'?`<p class="tp-meta">Stok bebas ${fmt(r.bebas)}</p>`:`<p>Disetujui <strong>${fmt(r.disetujui)}</strong></p><p class="tp-meta">Dipindahkan ${fmt(r.selesai_kg)}<br>${['selesai','gugur','ditolak'].includes(r.status)?'Sisa tidak dipindahkan':'Sisa persetujuan'} ${fmt(r.sisa)}</p>`}</div>
 <div class="tp-tujuan"><p>${esc(r.asal)} → ${r.status==='diminta'?esc(data.gudang_tujuan.nama):esc(tujuan(r))}</p>${Number(r.perjalanan_kg)>0?`<p class="tp-meta">Dalam perjalanan lama ${fmt(r.perjalanan_kg)}</p>`:''}</div>
 <div class="tp-aksi">${mode(r)?`<button class="btn btn--kecil" type="button" data-catatan="${r.id}">${mode(r)==='setujui'?'Periksa & setujui':'Catat transfer'}</button>`:`<button class="btn btn--kecil" type="button" data-detail="permintaan" data-id="${r.id}">Lihat detail</button>`}${mode(r)?`<button class="btn tp-menu" type="button" data-detail="permintaan" data-id="${r.id}" aria-label="Tindakan permintaan ${r.id}" aria-haspopup="dialog">⋯</button>`:''}</div></article>`).join('')||kosong('permintaan');
 $('#pk-jalan').innerHTML=js.map(j=>`<article class="tp-row" id="perjalanan-${j.id}"><span class="tp-pilih" aria-hidden="true"></span><div class="tp-lot"><h3>${j.pakai_kendaraan?'Perjalanan lama':'Transfer'} #${j.id}</h3><p>${j.items.map(i=>esc(i.lot)).join('<br>')}</p><p class="tp-meta">${esc(waktu(j.waktu))}</p>${badge(j.status)}</div><div class="tp-angka"><p>Total efektif <strong>${fmt(j.total)}</strong></p><p class="tp-meta">${j.items.length} lot</p></div><div class="tp-tujuan"><p>${esc(j.lintasan.asal.nama)} → ${esc(j.lintasan.tujuan.nama)}</p>${j.pakai_kendaraan?`<p class="tp-meta">${esc(j.nomor_polisi)} · ${esc(j.nama_sopir)}</p>`:''}</div><div class="tp-aksi"><button class="btn btn--kecil" type="button" data-detail="transfer" data-id="${j.id}">Lihat detail</button></div></article>`).join('')||kosong('transfer');
 const audits=(data.koreksi||[]).filter(k=>!$('#pk-cari').value.trim()||[k.alasan,...(k.ringkasan||[])].join(' ').toLowerCase().includes($('#pk-cari').value.trim().toLowerCase()));
 $('#pk-audit').innerHTML=data.admin&&audits.length?`<details><summary>Riwayat koreksi Admin · ${audits.length}</summary><ul>${audits.map(k=>`<li><strong>Koreksi #${k.id}</strong> · ${esc(waktu(k.waktu))}<p>${esc(k.alasan)}</p>${k.ringkasan?.length?`<ul>${k.ringkasan.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}</li>`).join('')}</ul></details>`:'';
 const f=filters[tab];$('#pk-filter-buka').textContent='Filter'+(Object.values(f).some(Boolean)?' · Aktif':'');
 $('#pk-ringkasan').textContent=(tab==='permintaan'?`${rs.length} dari ${data.permintaan.length} permintaan`:`${js.length} dari ${data.pengiriman.length} transfer terbaru`)+(f.status?' · '+(status[f.status]||f.status):' · Semua status');
 selected();
}
function rowsDipilih(){return data.permintaan.filter(r=>pilihan.has(r.id))}
function gabungan(rows){return rows.every(r=>r.asal_id===rows[0].asal_id&&r.silo_id===rows[0].silo_id&&r.pemilik_kunci===rows[0].pemilik_kunci)}
function selected(){
 const rows=rowsDipilih(),m=rows[0]&&mode(rows[0]),sah=rows.length<=50&&(m==='setujui'||gabungan(rows));
 $('#pk-pilihan').hidden=!rows.length;$('#pk-terpilih').textContent=`${rows.length} permintaan dipilih`;
 $('#pk-buka-form').textContent=m==='setujui'?`Periksa ${rows.length} permintaan`:`Catat transfer · ${rows.length} lot`;$('#pk-buka-form').disabled=!sah;
 $('#pk-pilihan-pesan').textContent=rows.length>50?'Pilih maksimal 50 permintaan sekaligus.':sah?(m==='kirim'?'Asal, tujuan, dan pemilik sama.':'Jumlah dan tujuan diperiksa per lot.'):'Pilih lot dengan asal, tujuan, dan pemilik yang sama untuk dicatat bersama.';
 return rows;
}
async function load(){
 if(busy)return;busy=true;root.setAttribute('aria-busy','true');$('#pk-muat').disabled=true;
 try{data=await api('');render();pesan('Status diperbarui.');return true}catch(e){pesan(e.message,true);return false}finally{busy=false;root.setAttribute('aria-busy','false');$('#pk-muat').disabled=false}
}
function bukaDetail(jenis,id){
 const r=jenis==='permintaan'?data.permintaan.find(x=>x.id===id):data.pengiriman.find(x=>x.id===id);if(!r)return;
 $('#pk-detail-judul').textContent=(jenis==='permintaan'?'Permintaan #':'Transfer #')+id;
 const dl=rows=>'<dl>'+rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')+'</dl>';
 let html;
 if(jenis==='permintaan'){
  html=`<h3>${esc(r.lot)}</h3><p>${esc(r.pemilik)}</p>${badge(fase(r))}`+dl([['Diminta oleh',r.peminta],['Waktu permintaan',waktu(r.waktu)],['Asal',r.asal],['Tujuan',r.status==='diminta'?'Menunggu pilihan Admin':tujuan(r)],['Diminta',fmt(r.diminta)],['Disetujui',fmt(r.disetujui)],['Sudah dipindahkan',fmt(r.selesai_kg)],['Dalam perjalanan lama',fmt(r.perjalanan_kg)],[['selesai','gugur','ditolak'].includes(r.status)?'Sisa tidak dipindahkan':'Sisa persetujuan',fmt(r.sisa)]]);
  if(r.sebab)html+=`<p>Alasan: ${esc(r.sebab)}</p>`;
  html+='<p class="bantu">Permintaan dan persetujuan belum mengurangi stok. Stok berubah ketika transfer dicatat.</p><div class="tp-actions">';
  if(mode(r))html+=`<button class="btn btn--utama" type="button" data-catatan="${r.id}">${mode(r)==='setujui'?'Periksa & setujui':'Catat transfer'}</button>`;
  if(data.admin){
   if(r.status==='diminta')html+=`<button class="btn" type="button" data-action="tolak" data-id="${r.id}">Tolak permintaan</button>`;
   if(['disetujui','dikirim'].includes(r.status)&&Number(r.sisa)>0)html+=`<button class="btn" type="button" data-action="tutup-sisa" data-id="${r.id}">Tutup sisa persetujuan</button>`;
   if(r.status==='diminta'||Number(r.disetujui)>0)html+=`<button class="btn" type="button" data-koreksi="permintaan" data-id="${r.id}">Koreksi permintaan</button>`;
  }
  const journeys=data.pengiriman.filter(j=>j.items.some(i=>i.permintaan_id===r.id));
  for(const j of journeys)html+=`<button class="btn" type="button" data-detail="transfer" data-id="${j.id}">Lihat transfer #${j.id} · ${fmt(j.total)}</button>`;
  html+='</div>';
 }else{
  html=badge(r.status)+dl([['Waktu pencatatan',waktu(r.waktu)],['Asal',r.lintasan.asal.nama],['Tujuan',r.lintasan.tujuan.nama],['Total transfer efektif',fmt(r.total)]]);
  if(r.pakai_kendaraan)html+=dl([['Nomor polisi',r.nomor_polisi],['Sopir',r.nama_sopir],['Hasil timbang',r.bobot_timbang_kg===null?'Belum tersedia':fmt(r.bobot_timbang_kg)],['Selisih',r.selisih_kg===null?'Belum tersedia':fmt(r.selisih_kg)]]);
  html+='<div class="tp-detail-lot">'+r.items.map(i=>`<h3>${esc(i.lot)}</h3><p>${fmt(i.berat_kg)}</p><div class="tp-actions"><button class="btn" type="button" data-detail="permintaan" data-id="${i.permintaan_id}">Lihat permintaan #${i.permintaan_id}</button>${i.transfer_id&&data.boleh_kirim?`<a class="btn" href="/riwayat-transfer/${i.transfer_id}">Rincian stok & bahan</a>`:''}${data.admin&&!r.pakai_kendaraan&&r.status==='selesai'&&Number(i.berat_kg)>0?`<button class="btn" type="button" data-koreksi="transfer" data-id="${i.id}">Koreksi jumlah</button>`:''}</div>`).join('')+'</div>';
  if(r.alasan)html+=`<p>Alasan: ${esc(r.alasan)}</p>`;
  html+='<div class="tp-actions">';
  if(r.pakai_kendaraan&&root.dataset.tera&&(r.tiket_id||r.status==='dalam_perjalanan'))html+=`<a class="btn" href="${esc(root.dataset.tera)}/timbangan/${r.tiket_id?'transaksi/'+r.tiket_id:'timbang/TRANSFER?pengiriman_pk_id='+r.id}">${r.tiket_id?'Lihat tiket timbang':'Buka timbang perjalanan'}</a>`;
  if(data.admin&&r.status==='menunggu_admin')html+=`<button class="btn" type="button" data-action="terima-selisih" data-id="${r.id}">Periksa & terima selisih</button>`;
  if(data.admin&&r.status==='dalam_perjalanan'&&!r.tiket_id)html+=`<button class="btn" type="button" data-action="batal" data-id="${r.id}">Batalkan perjalanan</button>`;
  html+='</div>';
 }
 $('#pk-detail-isi').innerHTML=html;if(!$('#pk-detail').open)$('#pk-detail').showModal();else $('#pk-detail').scrollTop=0;
}
function jumlahTransfer(r){
 const cents=Math.round(Number(r.sisa)*100);
 return `<div class="tp-jumlah" data-sisa="${esc(r.sisa)}"><label>Cara mengisi jumlah<select class="fld" name="cara"><option value="karung">Karung bekas 50 kg dan curah</option><option value="kg">Langsung dalam kg</option></select></label><div data-unit="karung"><label>Jumlah karung bekas 50 kg<input class="fld" name="jumlah_karung" type="number" min="0" step="1" inputmode="numeric" value="${Math.floor(cents/5000)}"></label><label>Curah / bagian karung (kg, boleh kosong)<input class="fld" name="berat_curah_kg" type="number" min="0" step="0.01" inputmode="decimal" value="${((cents%5000)/100).toFixed(2)}"></label></div><label data-unit="kg" hidden>Jumlah dipindahkan (kg)<input class="fld" name="berat" type="number" min="0.01" step="0.01" max="${esc(r.sisa)}" inputmode="decimal"></label><p class="tp-meta" data-total role="status"></p></div>`;
}
function perbaruiJumlah(row){
 const box=row.querySelector('.tp-jumlah');if(!box)return;
 const m=box.querySelector('[name=cara]').value;
 box.querySelectorAll('[data-unit]').forEach(g=>{g.hidden=g.dataset.unit!==m;g.querySelectorAll('input').forEach(x=>{x.disabled=g.hidden;x.setCustomValidity('')})});
 const n=Number(box.querySelector('[name=jumlah_karung]').value||0),c=Number(box.querySelector('[name=berat_curah_kg]').value||0),kg=m==='karung'?n*50+c:Number(box.querySelector('[name=berat]').value||0),cents=Math.round(kg*100),limit=Math.round(Number(box.dataset.sisa)*100);
 let error='';if(!Number.isFinite(kg)||kg<=0)error='Isi jumlah yang dipindahkan lebih dari nol.';else if(m==='karung'&&(!Number.isInteger(n)||n<0||c<0))error='Isi karung dalam bilangan bulat dan curah nol atau lebih.';else if(cents>limit)error='Total melebihi sisa persetujuan '+fmt(box.dataset.sisa)+'.';
 row.dataset.totalCents=String(cents);box.querySelector(m==='karung'?'[name=jumlah_karung]':'[name=berat]').setCustomValidity(error);
 box.querySelector('[data-total]').textContent='Total dipindahkan '+fmt(kg)+' · sisa persetujuan '+fmt(box.dataset.sisa)+(error?' · '+error:'');box.querySelector('[data-total]').toggleAttribute('data-galat',!!error);
}
function totalForm(){
 const rows=[...$('#pk-form-lot').children];let total=0;
 for(const r of rows){if(formAktif.mode==='kirim')perbaruiJumlah(r);total+=formAktif.mode==='kirim'?Number(r.dataset.totalCents||0):Math.round(Number(r.querySelector('[name=berat]').value||0)*100)}
 $('#pk-form-total').textContent=`Total ${formAktif.mode==='setujui'?'persetujuan':'transfer'} ${fmt(total/100)} · ${rows.length} lot`;
}
function bukaForm(rows){
 if(busy||!rows.length)return;
 const m=mode(rows[0]);if(!m||rows.some(r=>mode(r)!==m)||rows.length>50||m==='kirim'&&!gabungan(rows))return;
 $('#pk-detail').close();formAktif={mode:m,ids:rows.map(r=>r.id),kunci:crypto.randomUUID().replaceAll('-','')};pendingPayload=null;
 $('#pk-form-judul').textContent=m==='setujui'?'Setujui permintaan':'Catat transfer';
 $('#pk-form-arahan').textContent=m==='setujui'?'Periksa jumlah dan tujuan setiap lot. Persetujuan hanya mencadangkan stok, belum memindahkan barang.':'Catat jumlah yang benar-benar sudah dipindahkan. Penyimpanan mengurangi stok asal dan menambah stok tujuan. Transfer boleh sebagian.';
 $('#pk-form-lot').innerHTML=rows.map(r=>`<div class="tp-form-row" data-id="${r.id}"><h3>${esc(r.lot)} · Permintaan #${r.id}</h3><p class="tp-meta">${esc(r.pemilik)} · ${esc(r.asal)}${m==='kirim'?' → '+esc(tujuan(r)):''}</p>${m==='setujui'?`<p class="tp-meta">Diminta ${fmt(r.diminta)} · stok bebas ${fmt(r.bebas)}</p><label>Setujui (kg)<input class="fld" name="berat" type="number" min="0.01" max="${esc(r.bebas)}" step="0.01" inputmode="decimal" required value="${Math.min(Number(r.diminta),Number(r.bebas))}"></label><label>Tujuan<select class="fld" name="tujuan" required>${data.tujuan.map(t=>`<option value="${esc(t.nilai)}">${esc(t.nama)}</option>`).join('')}</select></label>`:jumlahTransfer(r)}</div>`).join('');
 $('#pk-simpan').textContent=m==='setujui'?`Setujui ${rows.length} permintaan`:`Catat transfer · ${rows.length} lot`;
 $('#pk-form-pesan').textContent='';kunciForm(false);totalForm();$('#pk-form').showModal();
}
function kunciForm(ya){
 $('#pk-form-lot').querySelectorAll('input,select').forEach(x=>x.disabled=ya||!!x.closest('[data-unit][hidden]'));
 $('#pk-form').querySelectorAll('[data-tutup]').forEach(b=>b.disabled=ya);
}
function muatan(row,m){const item={permintaan_id:Number(row.dataset.id)};if(m==='setujui')return {...item,berat_kg:row.querySelector('[name=berat]').value,tujuan:row.querySelector('[name=tujuan]').value};const cara=row.querySelector('[name=cara]').value;return cara==='karung'?{...item,cara,jumlah_karung:Number(row.querySelector('[name=jumlah_karung]').value||0),berat_curah_kg:row.querySelector('[name=berat_curah_kg]').value||'0'}:{...item,cara,berat_kg:row.querySelector('[name=berat]').value}}
$('#pk-catatan').addEventListener('input',e=>{if(e.target.name!=='cara')totalForm()});
$('#pk-catatan').addEventListener('change',e=>{
 if(e.target.name==='cara'){
  const row=e.target.closest('.tp-form-row'),cents=Number(row.dataset.totalCents||0);
  if(e.target.value==='kg')row.querySelector('[name=berat]').value=cents>0?(cents/100).toFixed(2):'';
  else{row.querySelector('[name=jumlah_karung]').value=cents>0?Math.floor(cents/5000):'';row.querySelector('[name=berat_curah_kg]').value=cents>0?((cents%5000)/100).toFixed(2):''}
 }totalForm();
});
$('#pk-catatan').addEventListener('submit',async e=>{
 e.preventDefault();if(busy||!formAktif)return;
 const m=formAktif.mode,body=pendingPayload||{items:[...$('#pk-form-lot').children].map(r=>muatan(r,m)),...(m==='kirim'?{kunci:formAktif.kunci}:{})};
 busy=true;$('#pk-simpan').disabled=true;kunciForm(true);$('#pk-form-pesan').textContent='Menyimpan…';
 try{
  const result=await api(m==='setujui'?'/setujui':'/pengiriman',body);pendingPayload=null;$('#pk-form').close();busy=false;
  if(m==='kirim')tab='riwayat';
  const fresh=await load();urlSimpan();pesan((m==='setujui'?'Permintaan dipilih telah disetujui.':`Transfer #${result.id} tercatat. Stok asal dan tujuan sudah diperbarui.`)+(fresh?'':' Daftar belum diperbarui. Tekan Perbarui status.'),!fresh);
 }catch(err){
  // Sesudah balasan terputus, payload dikunci untuk pengulangan idempoten.
  // Angka tidak boleh diedit menjadi kiriman baru sebelum hasilnya diketahui.
  pendingPayload=m==='kirim'&&!err.pasti?body:null;kunciForm(!!pendingPayload);
  $('#pk-form-pesan').textContent=err.message+(pendingPayload?' Isian dikunci. Tekan Ulangi pencatatan untuk memastikan hasil kiriman yang sama.':' Isian tetap tersedia. Periksa dan coba lagi.');$('#pk-form-pesan').setAttribute('data-galat','');
  if(pendingPayload)$('#pk-simpan').textContent='Ulangi pencatatan';
 }finally{busy=false;$('#pk-simpan').disabled=false}
});
$('#pk-form').addEventListener('cancel',e=>{if(busy||pendingPayload)e.preventDefault()});
root.addEventListener('change',e=>{
 if(e.target.name!=='pilih')return;const id=Number(e.target.value),r=data.permintaan.find(r=>r.id===id);
 if(e.target.checked){const old=rowsDipilih()[0];if(old&&mode(old)!==mode(r)){pilihan.clear();root.querySelectorAll('[name=pilih]').forEach(x=>x.checked=Number(x.value)===id)}pilihan.add(id)}else pilihan.delete(id);selected();
});
function filterBuka(){
 const f=filters[tab],form=$('#pk-filter-form'),opt=(v,n)=>`<option value="${esc(v)}">${esc(n)}</option>`;
 form.elements.status.innerHTML=opt('','Semua status')+(tab==='permintaan'?['diminta','perlu_transfer','siap','sebagian','selesai','ditutup','ditolak','gugur']:['selesai','dibatalkan','dalam_perjalanan','menunggu_admin']).map(k=>opt(k,status[k])).join('');
 const origins=new Map([...data.permintaan.map(r=>[r.asal_id,r.asal]),...data.pengiriman.map(j=>[j.lintasan.asal.gudang_id,j.lintasan.asal.nama])]);
 const targets=new Map([['ditumpuk','Tumpukan'],...data.permintaan.filter(r=>r.silo_id).map(r=>[String(r.silo_id),r.tujuan_nama]),...data.pengiriman.filter(j=>j.lintasan.tujuan.silo_id).map(j=>[String(j.lintasan.tujuan.silo_id),j.lintasan.tujuan.nama]),...data.tujuan.filter(t=>t.id).map(t=>[String(t.id),t.nama])]);
 form.elements.asal.innerHTML=opt('','Semua gudang asal')+[...origins].map(([v,n])=>opt(v,n)).join('');form.elements.tujuan.innerHTML=opt('','Semua tujuan')+[...targets].map(([v,n])=>opt(v,n)).join('');
 for(const k of ['status','asal','tujuan'])form.elements[k].value=f[k]||'';$('#pk-filter').showModal();
}
function semua(){filters[tab]={status:'',asal:'',tujuan:''};$('#pk-cari').value='';render();urlSimpan()}
$('#pk-filter-form').addEventListener('submit',e=>{e.preventDefault();for(const k of ['status','asal','tujuan'])filters[tab][k]=e.target.elements[k].value;$('#pk-filter').close();render();urlSimpan()});
$('#pk-filter-reset').onclick=()=>{$('#pk-filter').close();semua()};
$('#pk-pencarian').addEventListener('submit',e=>{e.preventDefault();render();urlSimpan()});
$('#pk-cari').addEventListener('input',()=>{if(data){render();urlSimpan()}});
$('#pk-filter-buka').onclick=()=>data&&filterBuka();
$('#pk-buka-form').onclick=()=>bukaForm(selected());
$('#pk-bersihkan').onclick=()=>{pilihan.clear();root.querySelectorAll('[name=pilih]').forEach(x=>x.checked=false);selected()};
root.addEventListener('click',e=>{
 const a=e.target.closest('[data-pk-tab]');if(a){e.preventDefault();if(data&&!busy){tab=a.dataset.pkTab;render();urlSimpan()}return}
 const close=e.target.closest('[data-tutup]');if(close&&!busy){close.closest('dialog').close();return}
 if(busy)return;
 if(e.target.closest('[data-semua]')){semua();return}
 const cat=e.target.closest('[data-catatan]');if(cat){bukaForm([data.permintaan.find(r=>r.id===Number(cat.dataset.catatan))]);return}
 const detail=e.target.closest('[data-detail]');if(detail){bukaDetail(detail.dataset.detail,Number(detail.dataset.id));return}
 if(e.target.closest('[data-koreksi]'))$('#pk-detail').close();
 const b=e.target.closest('[data-action]');if(!b||!data.admin)return;
 $('#pk-detail').close();decision={id:Number(b.dataset.id),action:b.dataset.action};
 $('#pk-alasan-judul').textContent=b.textContent;$('#pk-alasan-keterangan').textContent=decision.action==='tutup-sisa'?'Hanya sisa yang belum dipindahkan dilepas. Jumlah persetujuan asli dan transfer yang sudah tercatat tetap tersimpan. Tidak dapat ditutup selama ada perjalanan belum selesai.':decision.action==='terima-selisih'?'Periksa hasil timbang dan muatan lot di perjalanan. Menerima selisih mempertahankan bobot lot asal dan mencatat stok tujuan.':decision.action==='tolak'?'Permintaan ditolak tanpa memindahkan stok. Isi alasan agar operator mengetahui keputusannya.':'Perjalanan yang sudah memiliki tiket tidak dapat dibatalkan dari sini.';
 $('#pk-alasan-form').reset();$('#pk-alasan-pesan').textContent='';$('#pk-alasan').showModal();
});
$('#pk-alasan-form').addEventListener('submit',async e=>{
 e.preventDefault();if(busy)return;busy=true;const button=e.submitter;button.disabled=true;
 try{await api(['tolak','tutup-sisa'].includes(decision.action)?`/permintaan/${decision.id}/${decision.action}`:`/${decision.id}/${decision.action}`,{alasan:new FormData(e.target).get('alasan')});$('#pk-alasan').close();busy=false;await load();pesan('Keputusan tersimpan.')}catch(err){$('#pk-alasan-pesan').textContent=err.message+' Alasan tetap tersedia.';$('#pk-alasan-pesan').setAttribute('data-galat','')}finally{busy=false;button.disabled=false}
});
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
  formKoreksi.elements.tujuan.required=tujuan;
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
  if(row.silo_id&&!data.tujuan.some(t=>t.id===row.silo_id))formKoreksi.elements.tujuan.insertAdjacentHTML('afterbegin',`<option value="" selected disabled>${esc(row.tujuan_nama||'Silo lama')} tidak tersedia · pilih tujuan</option>`);
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

$('#pk-panduan-buka').onclick=()=>$('#pk-panduan').showModal();
$('#pk-cetak').onclick=()=>window.print();$('#pk-muat').onclick=load;
load().then(ok=>{if(!ok)return;const id=Number(qawal.get('pengiriman')||location.hash.replace('#perjalanan-',''));if(id&&data.pengiriman.some(j=>j.id===id))bukaDetail('transfer',id)});
})();
