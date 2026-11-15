(() => {
'use strict';
const root=document.querySelector('#transfer-pk');if(!root)return;
const $=s=>root.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:2})+' kg';
const waktu=s=>s?new Date(s).toLocaleString('id-ID',{dateStyle:'medium',timeStyle:'short'}):'Belum tercatat';
const jenisBarang={pk_giling:'PK hasil giling',pk_tumpukan:'PK tumpukan',barang:'Barang berkarung',curah_barang:'Barang curah',curah:'Hasil samping curah',karung:'Karung kosong',gabah:'Gabah',gabah_kering:'Gabah kering'};
const status={perlu_transfer:'Siap / sebagian',diminta:'Menunggu Admin',disetujui:'Siap dipindahkan',siap:'Siap dipindahkan',sebagian:'Dipindahkan sebagian',dikirim:'Dipindahkan sebagian',selesai:'Selesai',ditutup:'Sisa ditutup',ditolak:'Ditolak',gugur:'Tidak dilanjutkan',dalam_perjalanan:'Menunggu timbang',menunggu_admin:'Selisih · perlu Admin',dibatalkan:'Dibatalkan'};
let data,busy=false,decision,formAktif=null,pendingPayload=null;
const pilihan=new Set(),qawal=new URLSearchParams(location.search);
let tab=qawal.get('tab')==='riwayat'||qawal.has('pengiriman')||location.hash.startsWith('#perjalanan-')?'riwayat':'permintaan';
const filters={permintaan:{status:'',asal:'',tujuan:'',jenis:''},riwayat:{status:'',asal:'',tujuan:'',jenis:''}};
for(const k of ['status','asal','tujuan','jenis'])if(qawal.has(k))filters[tab][k]=qawal.get(k);
$('#pk-cari').value=(qawal.get('cari')||'').slice(0,200);
async function api(path,body){
 if(body)root.dispatchEvent(new Event('transfer-menulis'));
 const r=await fetch('/api/transfer-bertahap'+path,{method:body?'POST':'GET',cache:'no-store',headers:body?{'Content-Type':'application/json','x-csrf-token':root.dataset.csrf}:{},body:body?JSON.stringify(body):undefined});
 let d;try{d=await r.json()}catch{throw Error('Balasan belum dapat dibaca. Ulangi pencatatan dengan isian yang sama.')}
 if(!r.ok){const e=Error(typeof d.detail==='string'?d.detail:'Isian belum sah. Periksa jumlah dan pilihan.');e.pasti=r.status>=400&&r.status<500;throw e}return d;
}
function pesan(t,err=false){if(!root.isConnected)return;$('#pk-pesan').textContent=t;$('#pk-pesan').toggleAttribute('data-galat',err)}
function berhasil(t){if(!root.isConnected)return;pesan(t);const el=$('#pk-pesan');el.tabIndex=-1;el.focus({preventScroll:true})}
function fase(r){if(r.status==='disetujui')return Number(r.selesai_kg)>0?'sebagian':'siap';if(r.status==='dikirim')return 'sebagian';if(['selesai','gugur'].includes(r.status)&&Number(r.disetujui)>0&&Number(r.sisa)>0)return 'ditutup';return r.status}
function mode(r){return data.admin&&r.status==='diminta'&&Number(r.bebas)>0?'setujui':(r.boleh_catat??data.boleh_kirim)&&['disetujui','dikirim'].includes(r.status)&&Number(r.sisa)>0&&(r.id>0||Number(r.bebas)>0)?'kirim':''}
function totalKiriman(j){return [(Number(j.total)||!Number(j.lembar))?fmt(j.total):'',Number(j.lembar)?qfmt({satuan:'lembar'},j.lembar):''].filter(Boolean).join(' · ')}
function qfmt(r,n){return Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:2})+' '+(r.satuan||'kg')}
function ref(r){return r.nomor?(r.jenis_dokumen==='perintah'?'Perintah ':'')+r.nomor:(r.jenis_dokumen==='perintah'?'Perintah #':'Permintaan #')+r.id}
function tujuan(r){return [r.tujuan_pabrik||r.tujuan_lokasi?.pabrik_nama||'Pabrik belum ditetapkan',r.tujuan_gudang||r.tujuan_lokasi?.gudang_nama||data.gudang_tujuan.nama,r.tujuan_nama||data.tujuan.find(t=>t.id===r.silo_id)?.nama||(!r.silo_id?'Tumpukan':'Silo tidak tersedia')].filter(Boolean).join(' → ')}
function asal(r){return [r.asal_lokasi?.pabrik_nama||'Pabrik belum ditetapkan',r.asal_lokasi?.gudang_nama||r.asal].filter(Boolean).join(' → ')}
function lokasiRingkas(l){return [l?.pabrik_nama||'Pabrik belum ditetapkan',l?.gudang_nama||l?.nama,l?.penempatan].filter(Boolean).join(' → ')}
function badge(k){const flag=['selesai'].includes(k)?'done':['gugur','ditolak','dibatalkan','ditutup'].includes(k)?'cancel':'wait';return `<span class="riwayat-status riwayat-status--${flag}">${esc(status[k]||k)}</span>`}
function urlSimpan(){
 if(!root.isConnected)return;
 const q=new URLSearchParams();q.set('tab',tab);q.set('status',filters[tab].status||'');
 for(const [k,v] of Object.entries(filters[tab]))if(v)q.set(k,v);
 if($('#pk-cari').value.trim())q.set('cari',$('#pk-cari').value.trim());
 history.replaceState(history.state,'','/transfer-bertahap?'+q);
}
function tipe(r){return r.sumber_jenis||r.item?.sumber_jenis||'pk_giling'}
function targetKey(r,riwayat=false){const t=riwayat?r.lintasan.tujuan:r;return t.silo_id?'silo:'+t.silo_id:'gudang:'+(t.gudang_id||t.tujuan_id||data.gudang_tujuan.id)}
function cocok(r,riwayat=false){
 const f=filters[tab],q=$('#pk-cari').value.trim().toLocaleLowerCase('id-ID');
 const asal=riwayat?r.lintasan.asal.gudang_id:r.asal_id;
 const target=riwayat?r.lintasan.tujuan.silo_id:r.silo_id;
 const text=riwayat?[`Transfer #${r.id}`,r.nomor,...r.items.map(i=>i.pemilik),lokasiRingkas(r.lintasan.asal),lokasiRingkas(r.lintasan.tujuan),r.nomor_polisi,r.nama_sopir,r.lintasan.asal.nama,r.lintasan.tujuan.nama,...r.items.flatMap(i=>[i.lot,data.permintaan.find(x=>x.id===i.permintaan_id)?.pemilik])]:[r.lot,r.pemilik,r.peminta,r.asal,tujuan(r),`${esc(ref(r))}`];
 const statusCocok=!f.status||(!riwayat&&f.status==='perlu_transfer'?['siap','sebagian'].includes(fase(r)):(riwayat?r.status:fase(r))===f.status);
 return (!q||text.join(' ').toLocaleLowerCase('id-ID').includes(q))&&statusCocok&&(!f.asal||String(asal)===f.asal)&&(!f.jenis||tipe(r)===f.jenis)&&(!f.tujuan||targetKey(r,riwayat)===f.tujuan||(f.tujuan==='ditumpuk'&&!target));
}
function kosong(nama){return `<div class="tp-kosong"><h3>Tidak ada ${nama} yang sesuai</h3><p>Periksa pencarian atau tampilkan semua status.</p><button class="btn" type="button" data-semua>Tampilkan semua</button></div>`}
function riwayatRows(){
 return data.pengiriman.flatMap(j=>j.items.map((i,n)=>({...j,status:j.status==='selesai'&&Number(i.jumlah??i.berat_kg)===0?'dibatalkan':j.status,items:[i],item:i,nomor:i.nomor||j.nomor||`Transfer #${j.id}`,waktu:i.waktu||j.waktu,baris_kunci:`${j.id}-${n}`,urutan:n}))).sort((a,b)=>new Date(b.waktu)-new Date(a.waktu));
}
function renderRiwayat(rows){
 const unit=i=>Number(i.jumlah??i.berat_kg??0).toLocaleString('id-ID',{maximumFractionDigits:2})+' '+(i.satuan||'kg');
 const place=j=>j.item.sumber_jenis==='pk_tumpukan'?'Tumpukan':j.jenis_transfer==='barang'&&j.item.jenis_transfer!=='barang'?'Tumpukan':j.lintasan.tujuan.penempatan||j.lintasan.tujuan.nama.split(' · ')[0];
 const wh=(j,side)=>j.lintasan[side].gudang_nama||j.lintasan[side].nama;
 const site=(j,side)=>j.lintasan[side].pabrik_nama||'Pabrik belum ditetapkan';
 const label=j=>j.status==='selesai'?'Terkirim':status[j.status]||j.status;
 const flag=j=>j.status==='selesai'?'done':j.status==='dibatalkan'?'cancel':'wait';
 const link=j=>j.lama?`href="${esc(j.detail_url)}"`:`href="/transfer-bertahap?tab=riwayat&amp;pengiriman=${j.id}" data-detail="transfer" data-id="${j.id}"`;
 const owner=j=>j.item.nama_pemilik||j.item.pemilik||data.permintaan.find(r=>r.id===j.item.permintaan_id)?.pemilik||'Pabrik';
 const jasa=j=>j.item.jasa??!!j.item.jasa_id;
 const mass=rows.reduce((n,j)=>n+(j.status==='selesai'?Number(j.item.berat_kg||0):0),0),lembar=rows.reduce((n,j)=>n+(j.status==='selesai'&&j.item.satuan==='lembar'?Number(j.item.jumlah||0):0),0);
 $('#pk-history-stats').innerHTML=`<div><span>Catatan lot ditampilkan</span><strong>${rows.length}</strong></div><div><span>Total transfer efektif</span><strong>${fmt(mass)}${lembar?' · '+lembar.toLocaleString('id-ID')+' lembar':''}</strong></div><div><span>Catatan dibatalkan</span><strong>${rows.filter(j=>j.status==='dibatalkan').length}</strong></div>`;
 if(!rows.length){$('#pk-jalan').innerHTML=kosong('transfer');return}
 const mobile=rows.map(j=>`<article class="padat padat--diam padat--pindah_pk" data-history-card role="link" tabindex="0"><div><div class="padat__atas"><span class="padat__nama padat__nama--kode"><a ${link(j)}>${esc(j.nomor)}</a> · ${esc(new Date(j.waktu).toLocaleDateString('id-ID',{day:'2-digit',month:'2-digit'}))}</span><span class="padat__nilai ${j.status==='dibatalkan'?'padat__nilai--kosong':''}">${esc(unit(j.item))}</span></div><p class="tp-history-owner">${esc(owner(j))} <span class="riwayat-status riwayat-status--${jasa(j)?'jasa':'pabrik'}">${jasa(j)?'Jasa':'Bukan jasa'}</span></p><dl class="fakta"><div class="tp-history-lot"><dt>Barang / lot asal</dt><dd>${esc(j.item.lot)}</dd></div><div><dt>Asal</dt><dd>${esc(site(j,'asal'))}<small>${esc(wh(j,'asal'))}</small></dd></div><div><dt>Tujuan</dt><dd>${esc(site(j,'tujuan'))}<small>${esc(wh(j,'tujuan'))}</small><small>${esc(place(j))}</small></dd></div></dl><p><span class="riwayat-status riwayat-status--${flag(j)}">${esc(label(j))}</span></p>${j.status==='dibatalkan'?'<div class="nota nota--buruk"><span aria-hidden="true">✕</span><span>Catatan ini tidak dihitung sebagai transfer aktif.</span></div>':''}<a class="btn btn--kecil" ${link(j)}>Lihat detail lengkap →</a></div></article>`).join('');
 const desktop=rows.map(j=>`<details class="riwayat-desktop-row"><summary class="riwayat-desktop-grid riwayat-desktop-grid--transfer" data-history-card><span class="riwayat-desktop-lot"><strong><a ${link(j)}>${esc(j.nomor)}</a></strong><small>${esc(waktu(j.waktu))}</small></span><span class="riwayat-desktop-owner">${esc(owner(j))}<small><span class="riwayat-status riwayat-status--${jasa(j)?'jasa':'pabrik'}">${jasa(j)?'Jasa':'Bukan jasa'}</span></small></span><span>${esc(j.item.lot)}</span><span>${esc(site(j,'asal'))}<small class="tp-history-sub">${esc(wh(j,'asal'))}</small></span><span>${esc(site(j,'tujuan'))}<small class="tp-history-sub">${esc(wh(j,'tujuan'))}</small><small class="tp-history-sub">${esc(place(j))}</small></span><span class="riwayat-desktop-number">${esc(unit(j.item))}</span><span><span class="riwayat-status riwayat-status--${flag(j)}">${esc(label(j))}</span></span></summary></details>`).join('');
 $('#pk-jalan').innerHTML=`<div class="riwayat-list daftar-standar">${mobile}</div><div class="riwayat-desktop-list tabel-standar" aria-label="Daftar riwayat transfer"><div class="riwayat-desktop-grid riwayat-desktop-grid--transfer riwayat-desktop-head" aria-hidden="true"><span>Kode transfer / waktu</span><span>Nama pemilik</span><span>Barang / lot asal</span><span>Asal</span><span>Tujuan</span><span class="riwayat-desktop-number">Jumlah</span><span>Status transfer</span></div>${desktop}</div>`;
}
function renderPermintaan(rows){
 const doc=r=>`<a href="/transfer-bertahap?tab=permintaan&amp;permintaan=${r.id}" data-detail="permintaan" data-id="${r.id}">${esc(ref(r))}</a>`;
 const pilih=r=>mode(r)?`<label class="tp-pilih"><input type="checkbox" name="pilih" value="${r.id}" ${pilihan.has(r.id)?'checked':''} aria-label="Pilih ${esc(r.lot)} · ${esc(ref(r))}"><span class="sr-only">Pilih ${esc(ref(r))}</span></label>`:'';
 const nama=r=>`<span>${esc(r.pemilik)}</span><small>${r.jenis_dokumen==='perintah'?'Diperintahkan':'Diminta'} oleh ${esc(r.peminta)}</small>`;
 const jumlah=r=>{const siap=['disetujui','dikirim'].includes(r.status),akhir=['selesai','gugur'].includes(r.status);return `<strong>${qfmt(r,siap?r.sisa:akhir?r.selesai_kg:r.diminta)}</strong><small>${siap?(r.jenis_dokumen==='perintah'?'Sisa perintah':'Sisa persetujuan'):akhir?'Dipindahkan':r.jenis_dokumen==='perintah'?'Diperintahkan':'Diminta'}</small>${siap&&Number(r.selesai_kg)>0?`<small>${qfmt(r,r.selesai_kg)} sudah dipindahkan</small>`:''}`};
 const lokasi=(r,side)=>{const l=side==='asal'?r.asal_lokasi:r.tujuan_lokasi;return `<span>${esc(l?.pabrik_nama||'Pabrik belum ditetapkan')}</span><small>${esc(side==='asal'?l?.gudang_nama||r.asal:r.tujuan_gudang||l?.gudang_nama||data.gudang_tujuan.nama)}</small>${side==='tujuan'?`<small>${esc(r.tujuan_nama||'Menunggu pilihan Admin')}</small>`:''}`};
 const aksi=(r,desktop=false)=>`${badge(fase(r))}<div class="tp-actions">${mode(r)?`<button class="btn btn--kecil" type="button" data-catatan="${r.id}">${mode(r)==='setujui'?'Periksa & setujui':'Catat transfer'}</button>`:''}${!desktop||!mode(r)?`<button class="btn btn--kecil" type="button" data-detail="permintaan" data-id="${r.id}">Lihat detail</button>`:''}</div>`;
 $('#pk-request-stats').innerHTML=[['Menunggu Admin',rows.filter(r=>r.status==='diminta').length],['Siap / sebagian',rows.filter(r=>['siap','sebagian'].includes(fase(r))).length],['Selesai',rows.filter(r=>fase(r)==='selesai').length]].map(([label,n])=>`<div><span>${label}</span><strong>${n}</strong></div>`).join('');
 if(!rows.length){$('#pk-daftar').innerHTML=kosong('permintaan atau perintah');return}
 const mobile=rows.map(r=>`<article class="padat padat--diam padat--pindah_pk tp-request" data-request-id="${r.id}"><div><div class="padat__atas"><span class="tp-request-code">${pilih(r)}<span class="padat__nama padat__nama--kode">${doc(r)}<small>${esc(waktu(r.waktu))}</small></span></span><span class="padat__nilai">${qfmt(r,r.diminta)}</span></div><p class="tp-history-owner">${nama(r)}</p><dl class="fakta"><div class="tp-history-lot"><dt>Barang / lot asal</dt><dd>${esc(r.lot)}</dd></div><div><dt>Asal</dt><dd>${lokasi(r,'asal')}</dd></div><div><dt>Tujuan</dt><dd>${lokasi(r,'tujuan')}</dd></div></dl>${r.status!=='diminta'?`<p class="tp-meta">${r.jenis_dokumen==='perintah'?'Batas perintah':'Disetujui'} ${qfmt(r,r.disetujui)} · dipindahkan ${qfmt(r,r.selesai_kg)}<br>Sisa ${qfmt(r,r.sisa)}</p>`:''}<div class="tp-request-actions">${aksi(r)}</div></div></article>`).join('');
 const desktop=rows.map(r=>`<div class="riwayat-desktop-row"><div class="riwayat-desktop-grid riwayat-desktop-grid--transfer tp-request-grid"><span class="riwayat-desktop-lot tp-request-code">${pilih(r)}<span><strong>${doc(r)}</strong><small>${esc(waktu(r.waktu))}</small></span></span><span class="riwayat-desktop-owner">${nama(r)}</span><span>${esc(r.lot)}</span><span>${lokasi(r,'asal')}</span><span>${lokasi(r,'tujuan')}</span><span class="riwayat-desktop-number">${jumlah(r)}</span><span class="tp-request-actions">${aksi(r,true)}</span></div></div>`).join('');
 $('#pk-daftar').innerHTML=`<div class="riwayat-list daftar-standar">${mobile}</div><div class="riwayat-desktop-list tabel-standar" aria-label="Daftar permintaan dan perintah transfer"><div class="riwayat-desktop-grid riwayat-desktop-grid--transfer tp-request-grid riwayat-desktop-head" aria-hidden="true"><span>Dokumen / waktu</span><span>Nama pemilik</span><span>Barang / lot asal</span><span>Asal</span><span>Tujuan</span><span class="riwayat-desktop-number">Jumlah</span><span>Status / tindakan</span></div>${desktop}</div>`;
}
function render(){
 if(!data)return;
 root.querySelectorAll('[data-pk-tab]').forEach(a=>{if(a.dataset.pkTab===tab)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
 $('#pk-permintaan').hidden=tab!=='permintaan';$('#pk-perjalanan').hidden=tab!=='riwayat';
 $('#pk-jumlah-permintaan').textContent=data.permintaan.length;$('#pk-jumlah-riwayat').textContent=riwayatRows().length;
 $('#pk-arahan').textContent=tab==='riwayat'?'Buka detail untuk memeriksa transfer dan jejak koreksi.':data.admin?'Setujui permintaan operator atau buat perintah langsung. Stok berpindah saat operator asal mencatat pelaksanaan.':'Catat transfer yang siap setelah barang dipindahkan. Permintaan barang dapat diajukan untuk gudang kerja ini.';
 const rs=data.permintaan.filter(r=>cocok(r)),js=riwayatRows().filter(r=>cocok(r,true));
 renderPermintaan(rs);
 renderRiwayat(js);
 const audits=(data.koreksi||[]).filter(k=>!$('#pk-cari').value.trim()||[k.alasan,...(k.ringkasan||[])].join(' ').toLowerCase().includes($('#pk-cari').value.trim().toLowerCase()));
 $('#pk-audit').innerHTML=data.admin&&audits.length?`<details><summary>Riwayat koreksi Admin · ${audits.length}</summary><ul>${audits.map(k=>`<li><strong>Koreksi #${k.id}</strong> · ${esc(waktu(k.waktu))}<p>${esc(k.alasan)}</p>${k.ringkasan?.length?`<ul>${k.ringkasan.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}</li>`).join('')}</ul></details>`:'';
 const f=filters[tab];$('#pk-filter-buka').textContent='Filter'+(Object.values(f).some(Boolean)?' · Aktif':'');
 $('#pk-ringkasan').textContent=(tab==='permintaan'?`${rs.length} dari ${data.permintaan.length} permintaan`:`${js.length} dari ${riwayatRows().length} catatan lot`)+(f.status?' · '+(status[f.status]||f.status):' · Semua status');
 selected();
}
function rowsDipilih(){return data.permintaan.filter(r=>pilihan.has(r.id))}
function gabungan(rows){return rows.every(r=>r.asal_id===rows[0].asal_id&&(r.tujuan_id||data.gudang_tujuan.id)===(rows[0].tujuan_id||data.gudang_tujuan.id)&&r.silo_id===rows[0].silo_id&&r.pemilik_kunci===rows[0].pemilik_kunci)}
function selected(){
 const rows=rowsDipilih(),m=rows[0]&&mode(rows[0]),sah=rows.length<=50&&(m==='setujui'||gabungan(rows));
 $('#pk-pilihan').hidden=!rows.length;$('#pk-terpilih').textContent=`${rows.length} permintaan dipilih`;
 $('#pk-buka-form').textContent=m==='setujui'?`Periksa ${rows.length} permintaan`:`Catat transfer · ${rows.length} lot`;$('#pk-buka-form').disabled=!sah;
 $('#pk-pilihan-pesan').textContent=rows.length>50?'Pilih maksimal 50 permintaan sekaligus.':sah?(m==='kirim'?'Asal, tujuan, dan pemilik sama.':'Jumlah dan tujuan diperiksa per lot.'):'Pilih lot dengan asal, tujuan, dan pemilik yang sama untuk dicatat bersama.';
 return rows;
}
// GET dapat berjalan saat formulir terbuka. Respons ditahan sampai aman;
// hanya tindakan pengguna yang boleh mengirim/mengulang POST.
let membaca=false,ditunda=null,sidikData='',terakhirSegar=null,pengaturSegar=null,pembaca=null,putaranBaca=0;
const pasang=window.PINDAH?.pasang||((target,event,handler)=>target.addEventListener(event,handler));
function kesegaran(state,text){
 const el=$('#tp-segar');el.dataset.status=state;
 el.setAttribute('aria-live',state==='gagal'||state==='tertunda'?'polite':'off');
 el.textContent=text;$('#tp-coba-lagi').hidden=state!=='gagal';
}
function waktuSegar(){return terakhirSegar?terakhirSegar.toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit'}):'belum berhasil dimuat'}
function amanMenggambar(){
 if(busy||root.querySelector('dialog[open]')||pilihan.size)return false;
 const focus=document.activeElement;
 return !(root.contains(focus)&&(focus.matches('input,select,textarea')||$('#pk-daftar').contains(focus)||$('#pk-jalan').contains(focus)));
}
function terapkanData(next,force=false){
 if(!root.isConnected)return false;
 const sidik=JSON.stringify(next);
 if(sidik===sidikData){ditunda=null;kesegaran('segar','Data diperbarui pukul '+waktuSegar()+' · otomatis.');return true}
 if(!force&&!amanMenggambar()){
  ditunda=next;kesegaran('tertunda','Data baru tersedia. Daftar diperbarui setelah isian, pilihan, atau fokus selesai.');return true;
 }
 data=next;sidikData=sidik;ditunda=null;root._transferData=data;
 root.dispatchEvent(new CustomEvent('transfer-data',{detail:data}));render();
 $('#tp-permintaan-konteks').hidden=data.admin||!data.gudang_kerja;
 $('#tp-gudang-kerja').textContent=data.gudang_kerja?lokasiRingkas(data.gudang_kerja):'';
 kesegaran('segar','Data diperbarui pukul '+waktuSegar()+' · otomatis.');return true;
}
function terapkanTertunda(){if(ditunda&&amanMenggambar())terapkanData(ditunda)}
async function load({paksa=false}={}){
 if(!root.isConnected||busy)return false;
 if(membaca){if(!paksa)return false;pembaca?.abort()}
 const putaran=++putaranBaca;
 membaca=true;root.setAttribute('aria-busy','true');pembaca=new AbortController();
 if(!data)kesegaran('memuat','Memuat data…');
 try{
  const response=await fetch('/api/transfer-bertahap',{cache:'no-store',signal:pembaca.signal});
  if(!response.ok)throw Error(response.status===401?'Sesi perlu dibuka ulang. Muat ulang halaman setelah masuk.':'Data belum dapat diperbarui.');
  const next=await response.json();if(!root.isConnected||putaran!==putaranBaca)return false;
  terakhirSegar=new Date();return terapkanData(next,paksa||!data);
 }catch(e){if(root.isConnected&&putaran===putaranBaca&&e.name!=='AbortError'){ditunda=null;if(!data)$('#pk-arahan').textContent='Data transfer belum berhasil dimuat. Pilih Coba lagi untuk membaca daftar.';kesegaran('gagal','Gagal memperbarui data. Data terakhir '+waktuSegar()+'. '+e.message)}return false}
 finally{if(putaran===putaranBaca){membaca=false;if(root.isConnected)root.setAttribute('aria-busy','false')}}
}
function bacaLagi(){if(!document.hidden&&root.isConnected)load()}
function jadwalkanBaca(){pengaturSegar=setTimeout(()=>{if(!root.isConnected)return;bacaLagi();jadwalkanBaca()},60000)}
pasang(window,'focus',bacaLagi);pasang(window,'online',bacaLagi);
pasang(window,'offline',()=>{if(root.isConnected)kesegaran('gagal','Koneksi terputus. Menampilkan data terakhir '+waktuSegar()+'. Pembaruan dilanjutkan saat terhubung.')});
pasang(document,'visibilitychange',()=>{if(!document.hidden)bacaLagi()});
root.addEventListener('transfer-baca-segar',bacaLagi);
root.addEventListener('transfer-menulis',()=>{putaranBaca++;pembaca?.abort();membaca=false;ditunda=null;root.setAttribute('aria-busy','false')});
root.addEventListener('focusout',()=>setTimeout(terapkanTertunda,0));
root.addEventListener('close',()=>setTimeout(terapkanTertunda,0),true);
$('#tp-coba-lagi').onclick=bacaLagi;
const akhirHalaman=new MutationObserver(()=>{if(!root.isConnected){clearTimeout(pengaturSegar);pembaca?.abort();akhirHalaman.disconnect()}});
akhirHalaman.observe(document.body,{childList:true,subtree:true});jadwalkanBaca();
function bukaDetail(jenis,id){
 const r=jenis==='permintaan'?data.permintaan.find(x=>x.id===id):data.pengiriman.find(x=>x.id===id);if(!r)return;
 $('#pk-detail-judul').textContent=jenis==='permintaan'?ref(r):(r.nomor||'Transfer #'+id);
 const dl=rows=>'<dl>'+rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')+'</dl>';
 let html;
 if(jenis==='permintaan'){
  html=`<h3>${esc(r.lot)}</h3><p>${esc(r.pemilik)}</p>${badge(fase(r))}`+dl([[r.jenis_dokumen==='perintah'?'Diperintahkan oleh':'Diminta oleh',r.peminta],[r.jenis_dokumen==='perintah'?'Waktu perintah':'Waktu permintaan',waktu(r.waktu)],['Asal',asal(r)],['Tujuan',r.status==='diminta'&&r.id>0&&!r.multilokasi?'Menunggu pilihan Admin':tujuan(r)],[r.jenis_dokumen==='perintah'?'Diperintahkan':'Diminta',qfmt(r,r.diminta)],[r.jenis_dokumen==='perintah'?'Batas pelaksanaan':'Disetujui',qfmt(r,r.disetujui)],['Sudah dipindahkan',qfmt(r,r.selesai_kg)],['Dalam perjalanan lama',qfmt(r,r.perjalanan_kg)],[['selesai','gugur','ditolak'].includes(r.status)?'Sisa tidak dipindahkan':'Sisa persetujuan',qfmt(r,r.sisa)]]);
  if(r.sebab)html+=`<p>Alasan: ${esc(r.sebab)}</p>`;
  html+='<p class="bantu">Permintaan dan persetujuan belum mengurangi stok. Stok berubah ketika transfer dicatat.</p><div class="tp-actions">';
  if(mode(r))html+=`<button class="btn btn--utama" type="button" data-catatan="${r.id}">${mode(r)==='setujui'?'Periksa & setujui':'Catat transfer'}</button>`;
  if(data.admin){
   if(r.status==='diminta')html+=`<button class="btn" type="button" data-action="tolak" data-id="${r.id}">Tolak permintaan</button>`;
   if(['disetujui','dikirim'].includes(r.status)&&Number(r.sisa)>0)html+=`<button class="btn" type="button" data-action="tutup-sisa" data-id="${r.id}">${r.jenis_dokumen==='perintah'?'Tutup sisa perintah':'Tutup sisa persetujuan'}</button>`;
   if(r.status==='diminta'||Number(r.disetujui)>0)html+=`<button class="btn" type="button" data-koreksi="permintaan" data-id="${r.id}">${r.jenis_dokumen==='perintah'?'Koreksi perintah':'Koreksi permintaan'}</button>`;
  }
  const journeys=data.pengiriman.filter(j=>j.items.some(i=>i.permintaan_id===r.id));
  for(const j of journeys)html+=`<button class="btn" type="button" data-detail="transfer" data-id="${j.id}">${esc(j.nomor||'Transfer #'+j.id)} · ${totalKiriman(j)}</button>`;
  html+='</div>';
 }else{
  html=badge(r.status)+dl([['Waktu pencatatan',waktu(r.waktu)],['Asal',lokasiRingkas(r.lintasan.asal)],['Tujuan',lokasiRingkas(r.lintasan.tujuan)],['Total transfer efektif',totalKiriman(r)]]);
  if(r.pakai_kendaraan)html+=dl([['Nomor polisi',r.nomor_polisi],['Sopir',r.nama_sopir],['Hasil timbang',r.bobot_timbang_kg===null?'Belum tersedia':fmt(r.bobot_timbang_kg)],['Selisih',r.selisih_kg===null?'Belum tersedia':fmt(r.selisih_kg)]]);
  html+='<div class="tp-detail-lot">'+r.items.map(i=>`<h3>${esc(i.lot)}</h3><p>${qfmt(i,i.jumlah??i.berat_kg)}${i.satuan==='karung'?' · '+fmt(i.berat_kg):''}</p><div class="tp-actions"><button class="btn" type="button" data-detail="permintaan" data-id="${i.permintaan_id}">Lihat ${esc(ref(data.permintaan.find(r=>r.id===i.permintaan_id)||{id:i.permintaan_id}))}</button>${i.transfer_id&&data.boleh_kirim?`<a class="btn" href="/riwayat-transfer/${i.transfer_id}">Rincian stok & bahan</a>`:''}${data.admin&&!r.pakai_kendaraan&&(i.id<0||r.status==='selesai'&&Number(i.berat_kg)>0)?`<button class="btn" type="button" data-koreksi="transfer" data-id="${i.id}">Koreksi jumlah</button>`:''}</div>`).join('')+'</div>';
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
 if(r.id<0)return `<label>Jumlah dipindahkan (${esc(r.satuan)})<input class="fld" name="berat" type="number" min="${r.satuan==='kg'?'0.01':'1'}" max="${esc(r.sisa)}" step="${r.satuan==='kg'?'0.01':'1'}" inputmode="decimal" value="${esc(r.sisa)}" required ${r.seluruh?'readonly':''}></label>${r.seluruh?'<p class="tp-meta">Lot ini dipindahkan utuh sebelum dipakai proses.</p>':''}`;
 const cents=Math.round(Number(r.sisa)*100);
 return `<div class="tp-jumlah" data-sisa="${esc(r.sisa)}"><label>Cara mengisi jumlah<select class="fld" name="cara"><option value="karung">Karung bekas 50 kg dan curah</option><option value="kg">Langsung dalam kg</option></select></label><div data-unit="karung"><label>Jumlah karung bekas 50 kg<input class="fld" name="jumlah_karung" type="number" min="0" step="1" inputmode="numeric" value="${Math.floor(cents/5000)}"></label><label>Curah / bagian karung (kg, boleh kosong)<input class="fld" name="berat_curah_kg" type="number" min="0" step="0.01" inputmode="decimal" value="${((cents%5000)/100).toFixed(2)}"></label></div><label data-unit="kg" hidden>Jumlah dipindahkan (kg)<input class="fld" name="berat" type="number" min="0.01" step="0.01" max="${esc(r.sisa)}" inputmode="decimal"></label><p class="tp-meta" data-total role="status"></p></div>`;
}
function perbaruiJumlah(row){
 if(Number(row.dataset.id)<0){row.dataset.totalCents=String(Math.round(Number(row.querySelector('[name=berat]').value||0)*100));return}
 const box=row.querySelector('.tp-jumlah');if(!box)return;
 const m=box.querySelector('[name=cara]').value;
 box.querySelectorAll('[data-unit]').forEach(g=>{g.hidden=g.dataset.unit!==m;g.querySelectorAll('input').forEach(x=>{x.disabled=g.hidden;x.setCustomValidity('')})});
 const n=Number(box.querySelector('[name=jumlah_karung]').value||0),c=Number(box.querySelector('[name=berat_curah_kg]').value||0),kg=m==='karung'?n*50+c:Number(box.querySelector('[name=berat]').value||0),cents=Math.round(kg*100),limit=Math.round(Number(box.dataset.sisa)*100);
 let error='';if(!Number.isFinite(kg)||kg<=0)error='Isi jumlah yang dipindahkan lebih dari nol.';else if(m==='karung'&&(!Number.isInteger(n)||n<0||c<0))error='Isi karung dalam bilangan bulat dan curah nol atau lebih.';else if(cents>limit)error='Total melebihi sisa persetujuan '+fmt(box.dataset.sisa)+'.';
 row.dataset.totalCents=String(cents);box.querySelector(m==='karung'?'[name=jumlah_karung]':'[name=berat]').setCustomValidity(error);
 box.querySelector('[data-total]').textContent='Total dipindahkan '+fmt(kg)+' · sisa persetujuan '+fmt(box.dataset.sisa)+(error?' · '+error:'');box.querySelector('[data-total]').toggleAttribute('data-galat',!!error);
}
function totalForm(){
 const totals={};const rows=[...$('#pk-form-lot').children];
 for(const row of rows){
  const r=data.permintaan.find(r=>r.id===Number(row.dataset.id));
  if(formAktif.mode==='kirim')perbaruiJumlah(row);
  const n=formAktif.mode==='kirim'?Number(row.dataset.totalCents||0)/100:Number(row.querySelector('[name=berat]').value||0);
  const u=r.satuan||'kg';totals[u]=(totals[u]||0)+n;
 }
 $('#pk-form-total').textContent=`Total ${formAktif.mode==='setujui'?'persetujuan':'transfer'} `+Object.entries(totals).map(([u,n])=>qfmt({satuan:u},n)).join(' · ')+` · ${rows.length} lot`;
}

function bukaForm(rows){
 if(busy||!rows.length)return;
 const m=mode(rows[0]);if(!m||rows.some(r=>mode(r)!==m)||rows.length>50||m==='kirim'&&!gabungan(rows))return;
 $('#pk-detail').close();formAktif={mode:m,ids:rows.map(r=>r.id),kunci:crypto.randomUUID().replaceAll('-','')};pendingPayload=null;
 $('#pk-form-judul').textContent=m==='setujui'?'Setujui permintaan':'Catat transfer';
 $('#pk-form-arahan').textContent=m==='setujui'?'Periksa jumlah dan tujuan setiap lot. Persetujuan menetapkan batas jumlah; stok belum dipindahkan dan diperiksa lagi saat pencatatan.':'Catat jumlah yang benar-benar sudah dipindahkan. Penyimpanan mengurangi stok asal dan menambah stok tujuan. Transfer boleh sebagian.';
 $('#pk-form-lot').innerHTML=rows.map(r=>`<div class="tp-form-row" data-id="${r.id}"><h3>${esc(r.lot)} · ${esc(ref(r))}</h3><p class="tp-meta">${esc(r.pemilik)} · ${esc(r.asal)}${m==='kirim'?' → '+esc(tujuan(r)):''}</p>${m==='setujui'?`<p class="tp-meta">Diminta ${qfmt(r,r.diminta)} · stok bebas ${qfmt(r,r.bebas)}</p><label>Setujui (${esc(r.satuan||'kg')})<input class="fld" name="berat" type="number" min="${r.satuan&&r.satuan!=='kg'?'1':'0.01'}" max="${esc(r.bebas)}" step="${r.satuan&&r.satuan!=='kg'?'1':'0.01'}" inputmode="decimal" required value="${r.seluruh?Number(r.bebas):Math.min(Number(r.diminta),Number(r.bebas))}" ${r.seluruh?'readonly':''}></label><label>Tujuan<select class="fld" name="tujuan" required>${(r.id<0?data.tujuan_barang.filter(t=>t.id!==r.asal_id&&(!r.company_id||t.company_id===r.company_id)):r.multilokasi?data.tujuan_pk.filter(t=>t.gudang_id!==r.asal_id&&t.company_id===r.company_id):data.tujuan).map(t=>`<option value="${esc(t.nilai)}" ${(r.id<0?t.id===r.tujuan_id:r.multilokasi?t.nilai===targetKey(r):false)?'selected':''}>${esc(t.nama)}</option>`).join('')}</select></label>`:jumlahTransfer(r)}</div>`).join('');
 $('#pk-simpan').textContent=m==='setujui'?`Setujui ${rows.length} permintaan`:`Catat transfer · ${rows.length} lot`;
 $('#pk-form-pesan').textContent='';kunciForm(false);totalForm();$('#pk-form').showModal();
}
function kunciForm(ya){
 $('#pk-form-lot').querySelectorAll('input,select').forEach(x=>x.disabled=ya||!!x.closest('[data-unit][hidden]'));
 $('#pk-form').querySelectorAll('[data-tutup]').forEach(b=>b.disabled=ya);
}
function muatan(row,m){const item={permintaan_id:Number(row.dataset.id)};if(m==='setujui')return {...item,berat_kg:row.querySelector('[name=berat]').value,tujuan:row.querySelector('[name=tujuan]').value};if(item.permintaan_id<0)return {...item,berat_kg:row.querySelector('[name=berat]').value};const cara=row.querySelector('[name=cara]').value;return cara==='karung'?{...item,cara,jumlah_karung:Number(row.querySelector('[name=jumlah_karung]').value||0),berat_curah_kg:row.querySelector('[name=berat_curah_kg]').value||'0'}:{...item,cara,berat_kg:row.querySelector('[name=berat]').value}}
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
  const result=await api(m==='setujui'?'/setujui':'/pengiriman',body);pendingPayload=null;$('#pk-form').close();busy=false;pilihan.clear();
  if(m==='kirim')tab='riwayat';
  const fresh=await load({paksa:true});urlSimpan();berhasil((m==='setujui'?'Permintaan dipilih telah disetujui.':`Transfer tercatat. Stok asal dan tujuan sudah diperbarui.`)+(fresh?'':' Daftar belum diperbarui. Periksa indikator data dan pilih Coba lagi bila pembacaan gagal.'),!fresh);
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
 if(e.target.checked){const old=rowsDipilih()[0];if(old&&mode(old)!==mode(r)){pilihan.clear();root.querySelectorAll('[name=pilih]').forEach(x=>x.checked=Number(x.value)===id)}pilihan.add(id)}else pilihan.delete(id);root.querySelectorAll('[name=pilih]').forEach(x=>x.checked=pilihan.has(Number(x.value)));selected();terapkanTertunda();
});
function filterBuka(){
 const f=filters[tab],form=$('#pk-filter-form'),opt=(v,n)=>`<option value="${esc(v)}">${esc(n)}</option>`;
 form.elements.jenis.innerHTML=opt('','Semua jenis')+Object.entries(jenisBarang).map(([k,n])=>opt(k,n)).join('');
 form.elements.status.innerHTML=opt('','Semua status')+(tab==='permintaan'?['diminta','perlu_transfer','siap','sebagian','selesai','ditutup','ditolak','gugur']:['selesai','dibatalkan','dalam_perjalanan','menunggu_admin']).map(k=>opt(k,status[k])).join('');
 const origins=new Map([...data.permintaan.map(r=>[r.asal_id,asal(r)]),...data.pengiriman.map(j=>[j.lintasan.asal.gudang_id,lokasiRingkas(j.lintasan.asal)])]);
 const targets=new Map([...data.permintaan.map(r=>[targetKey(r),tujuan(r)]),...data.pengiriman.map(j=>[targetKey(j,true),lokasiRingkas(j.lintasan.tujuan)])]);
 form.elements.asal.innerHTML=opt('','Semua gudang asal')+[...origins].map(([v,n])=>opt(v,n)).join('');form.elements.tujuan.innerHTML=opt('','Semua tujuan')+[...targets].map(([v,n])=>opt(v,n)).join('');
 for(const k of ['status','asal','tujuan','jenis'])form.elements[k].value=f[k]||'';$('#pk-filter').showModal();
}
function semua(){filters[tab]={status:'',asal:'',tujuan:'',jenis:''};$('#pk-cari').value='';render();urlSimpan()}
$('#pk-filter-form').addEventListener('submit',e=>{e.preventDefault();for(const k of ['status','asal','tujuan','jenis'])filters[tab][k]=e.target.elements[k].value;$('#pk-filter').close();render();urlSimpan()});
$('#pk-filter-reset').onclick=()=>{$('#pk-filter').close();semua()};
$('#pk-pencarian').addEventListener('submit',e=>{e.preventDefault();render();urlSimpan()});
$('#pk-cari').addEventListener('input',()=>{if(data){render();urlSimpan()}});
$('#pk-filter-buka').onclick=()=>data&&filterBuka();
$('#pk-buka-form').onclick=()=>bukaForm(selected());
$('#pk-bersihkan').onclick=()=>{pilihan.clear();root.querySelectorAll('[name=pilih]').forEach(x=>x.checked=false);selected();terapkanTertunda()};
root.addEventListener('click',e=>{
 const a=e.target.closest('[data-pk-tab]');if(a){e.preventDefault();if(data&&!busy){tab=a.dataset.pkTab;render();urlSimpan()}return}
 const close=e.target.closest('[data-tutup]');if(close&&!busy){close.closest('dialog').close();return}
 if(busy)return;
 if(e.target.closest('[data-semua]')){semua();return}
 const cat=e.target.closest('[data-catatan]');if(cat){bukaForm([data.permintaan.find(r=>r.id===Number(cat.dataset.catatan))]);return}
 const detail=e.target.closest('[data-detail]');if(detail){e.preventDefault();bukaDetail(detail.dataset.detail,Number(detail.dataset.id));return}
 const card=e.target.closest('[data-history-card]');if(card&&!e.target.closest('a')){e.preventDefault();card.querySelector('a').click();return}
 if(e.target.closest('[data-koreksi]'))$('#pk-detail').close();
 const b=e.target.closest('[data-action]');if(!b||!data.admin)return;
 $('#pk-detail').close();decision={id:Number(b.dataset.id),action:b.dataset.action};
 $('#pk-alasan-judul').textContent=b.textContent;$('#pk-alasan-keterangan').textContent=decision.action==='tutup-sisa'?'Hanya sisa yang belum dipindahkan dilepas. Jumlah persetujuan asli dan transfer yang sudah tercatat tetap tersimpan. Tidak dapat ditutup selama ada perjalanan belum selesai.':decision.action==='terima-selisih'?'Periksa hasil timbang dan muatan lot di perjalanan. Menerima selisih mempertahankan bobot lot asal dan mencatat stok tujuan.':decision.action==='tolak'?'Permintaan ditolak tanpa memindahkan stok. Isi alasan agar operator mengetahui keputusannya.':'Perjalanan yang sudah memiliki tiket tidak dapat dibatalkan dari sini.';
 $('#pk-alasan-form').reset();$('#pk-alasan-pesan').textContent='';$('#pk-alasan').showModal();
});
$('#pk-alasan-form').addEventListener('submit',async e=>{
 e.preventDefault();if(busy)return;busy=true;const button=e.submitter;button.disabled=true;
 try{await api(['tolak','tutup-sisa'].includes(decision.action)?`/permintaan/${decision.id}/${decision.action}`:`/${decision.id}/${decision.action}`,{alasan:new FormData(e.target).get('alasan')});$('#pk-alasan').close();busy=false;pilihan.clear();await load({paksa:true});berhasil('Keputusan tersimpan.')}catch(err){$('#pk-alasan-pesan').textContent=err.message+' Alasan tetap tersedia.';$('#pk-alasan-pesan').setAttribute('data-galat','')}finally{busy=false;button.disabled=false}
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
  formKoreksi.elements.berat_kg.min=aksi==='jumlah'?'0':koreksiAktif.row.satuan&&koreksiAktif.row.satuan!=='kg'?'1':'0.01';
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
  $('#pk-koreksi-arahan').textContent=id<0?'Koreksi oleh Admin sesuai barang sebenarnya. Bagian yang sudah dipakai atau berpindah lagi harus diperbaiki melalui catatan lanjutannya terlebih dahulu.':'Koreksi oleh Admin sesuai barang sebenarnya. Pengurangan memakai tumpukan dahulu, kemudian silo dan bahan proses. Hasil ukur produksi tetap.';
  $('#pk-koreksi-judul').textContent=jenis==='transfer'?'Koreksi jumlah transfer':'Koreksi permintaan';
  $('#pk-koreksi-lot').textContent=row.lot+(jenis==='transfer'?' · saat ini '+qfmt(row,row.jumlah??row.berat_kg):' · '+(status[row.status]||row.status));
  let pilihan;
  if(jenis==='transfer')pilihan=[['jumlah','Jumlah transfer (0 = batal)'],...(row.pemindahan?.length?[['bahan','Bahan dari tumpukan']]:[])];
  else if(row.status==='diminta')pilihan=[['minta','Betulkan jumlah yang diminta'],['batal','Batalkan permintaan']];
  else if(['disetujui','dikirim'].includes(row.status))pilihan=[['persetujuan','Betulkan persetujuan'],...(Number(row.selesai_kg)===0?[['kembali','Kembalikan ke sebelum persetujuan'],['batal','Batalkan permintaan']]:[])];
  else pilihan=Number(row.disetujui)>0?[['persetujuan','Betulkan persetujuan'],['buka','Buka kembali sisa persetujuan']]:[];
  if(!pilihan.length){pesan('Permintaan sudah tidak aktif. Buat permintaan baru dari lot yang benar.',true);return}
  formKoreksi.elements.aksi.innerHTML=pilihan.map(([v,t])=>`<option value="${v}">${esc(t)}</option>`).join('');
  $('#pk-koreksi-unit').textContent='Jumlah yang benar ('+(row.satuan||'kg')+')';
  formKoreksi.elements.berat_kg.step=row.satuan&&row.satuan!=='kg'?'1':'0.01';
  formKoreksi.elements.berat_kg.value=jenis==='transfer'?(row.jumlah??row.berat_kg):row.status==='diminta'?row.diminta:row.disetujui;
  formKoreksi.elements.tujuan.innerHTML=(id<0?data.tujuan_barang.filter(t=>t.id!==row.asal_id&&(!row.company_id||t.company_id===row.company_id)):row.multilokasi?data.tujuan_pk.filter(t=>t.gudang_id!==row.asal_id&&t.company_id===row.company_id):data.tujuan).map(t=>`<option value="${esc(t.nilai)}" ${(id<0?t.id===row.tujuan_id:row.multilokasi?t.nilai===targetKey(row):t.id===row.silo_id||!row.silo_id&&t.nilai==='ditumpuk')?'selected':''}>${esc(t.nama)}</option>`).join('');
  if(row.silo_id&&!row.multilokasi&&!data.tujuan.some(t=>t.id===row.silo_id))formKoreksi.elements.tujuan.insertAdjacentHTML('afterbegin',`<option value="" selected disabled>${esc(row.tujuan_nama||'Silo lama')} tidak tersedia · pilih tujuan</option>`);
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
      }else if(koreksiAktif.jenis==='transfer')formKoreksi.elements.berat_kg.value=koreksiAktif.row.jumlah??koreksiAktif.row.berat_kg;
    }
    if(e.target.name==='pemindahan_id'&&formKoreksi.elements.aksi.value==='bahan'){
      const m=koreksiAktif.row.pemindahan.find(m=>String(m.id)===e.target.value);if(m)formKoreksi.elements.berat_kg.value=m.berat_kg;
    }
    bersihkanDampak();aturKoreksi()
  }
});
function tampilkanDampak(p){
  if(p.barang){
    const rows=p.barang.map(x=>`<tr><td>${esc(x.label)}</td><td>${esc(qfmt(x,x.sebelum))}</td><td>${esc(qfmt(x,x.sesudah))}</td></tr>`).join('');
    $('#pk-koreksi-dampak').innerHTML=`<h3>Dampak sebelum disimpan</h3><p>${esc(p.penjelasan)}</p><div class="tp-tabel"><table><thead><tr><th>Catatan</th><th>Sebelum</th><th>Sesudah</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    $('#pk-koreksi-dampak').hidden=false;$('#pk-koreksi-konfirmasi').hidden=false;return;
  }
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
  for(const x of p.barang_lokasi||[])rows+=baris('Transfer lokasi '+x.kode,x.before.jumlah,x.after.jumlah);
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
      $('#pk-koreksi').close();busy=false;pilihan.clear();await load({paksa:true});berhasil(`Koreksi #${result.peristiwa_id} tersimpan. Saldo dan catatan terkait sudah diperbarui.`);
    }
  }catch(err){$('#pk-koreksi-pesan').textContent=err.message+' Isian tetap tersedia.';$('#pk-koreksi-pesan').setAttribute('data-galat','')}
  finally{busy=false;button.disabled=tahap==='simpan'&&!formKoreksi.elements.konfirmasi.checked}
});

root.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-history-card][role=link]')){e.preventDefault();e.target.querySelector('a').click()}});
root.addEventListener('transfer-perbarui',e=>{pilihan.clear();load({paksa:true}).then(()=>{urlSimpan();if(e.detail?.pesan)berhasil(e.detail.pesan+(Object.values(filters[tab]).some(Boolean)||$('#pk-cari').value?' Filter aktif tetap dipakai.':''))})});
$('#pk-panduan-buka').onclick=()=>$('#pk-panduan').showModal();
$('#pk-cetak').onclick=()=>window.print();
load().then(ok=>{if(!ok)return;const id=Number(qawal.get('pengiriman')||location.hash.replace('#perjalanan-',''));if(id&&data.pengiriman.some(j=>j.id===id))bukaDetail('transfer',id);const request=Number(qawal.get('permintaan'));if(request&&data.permintaan.some(r=>r.id===request))bukaDetail('permintaan',request)});
})();
