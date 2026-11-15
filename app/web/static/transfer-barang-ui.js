(() => {
'use strict';
const root=document.querySelector('#transfer-pk');if(!root)return;
const $=s=>root.querySelector(s),panel=$('#tb-panel'),form=$('#tb-form'),search=$('#tb-cari-form');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const qty=(n,u)=>Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:2})+' '+u;
const loc=l=>[l?.pabrik_nama||'Pabrik belum ditetapkan',l?.gudang_nama].filter(Boolean).join(' → ');
let list=[],warehouses=[],selected=null,position=0,busy=false,key='',pending=null,queued=false,modeAktif='permintaan';
const data=()=>root._transferData||{};
const perintah=()=>modeAktif==='perintah';
function message(t,error=false){$('#tb-pesan').textContent=t;$('#tb-pesan').toggleAttribute('data-galat',error)}
async function api(path,body){
 if(body)root.dispatchEvent(new Event('transfer-menulis'));
 const r=await fetch('/api/transfer-barang'+path,{method:body?'POST':'GET',cache:'no-store',headers:body?{'Content-Type':'application/json','x-csrf-token':root.dataset.csrf}:{},body:body?JSON.stringify(body):undefined});
 let d;try{d=await r.json()}catch{throw Error('Balasan belum dapat dibaca. Coba lagi dengan isian yang sama.')}
 if(!r.ok){const e=Error(typeof d.detail==='string'?d.detail:'Periksa sumber, jumlah, dan tujuan.');e.pasti=r.status>=400&&r.status<500;throw e}return d;
}
function options(values){return '<option value="">Pilih…</option>'+values.map(([id,name])=>`<option value="${id}">${esc(name)}</option>`).join('')}
function destinations(){return warehouses.filter(w=>w.company_id===selected.company_id&&w.id!==selected.asal_id&&(perintah()||w.id===data().gudang_kerja?.gudang_id))}
function factories(){
 const names=new Map(destinations().map(w=>[w.pabrik_id,w.pabrik_nama]));
 form.elements.pabrik.innerHTML=options([...names]);if(names.size===1)form.elements.pabrik.value=String([...names.keys()][0]);warehouseOptions();
}
function warehouseOptions(){
 const rows=destinations().filter(w=>String(w.pabrik_id)===form.elements.pabrik.value);
 form.elements.gudang.innerHTML=options(rows.map(w=>[w.id,w.gudang_nama]));if(rows.length===1)form.elements.gudang.value=String(rows[0].id);
 destinationLocation();
}
function destinationLocation(){
 const silo=perintah()&&selected?.jenis==='pk_giling';
 $('#tb-lokasi-label').hidden=silo;$('#tb-tujuan-lokasi-label').hidden=!silo;
 const input=form.elements.tujuan_lokasi;input.disabled=!silo;input.required=silo;
 if(silo){const rows=(data().tujuan_pk||[]).filter(t=>String(t.gudang_id)===form.elements.gudang.value&&t.company_id===selected.company_id);input.innerHTML=rows.map(t=>`<option value="${esc(t.nilai)}">${esc(t.nama)}</option>`).join('')}
 $('#tb-lokasi-tujuan').value=['pk_giling','pk_tumpukan'].includes(selected?.jenis)?'Tumpukan':'Area stok';
}
function units(){
 const pk=selected?.jenis==='pk_giling',bags=pk&&form.elements.cara_pk.value==='karung';
 $('#tb-pk-unit').hidden=!pk;$('#tb-pk-karung').hidden=!bags;$('#tb-kg-label').hidden=bags;
 form.elements.cara_pk.disabled=!pk;form.elements.karung_pk.disabled=!bags;form.elements.curah_pk.disabled=!bags;
 form.elements.karung_pk.setCustomValidity('');
 form.elements.jumlah.readOnly=bags||!!selected?.seluruh;
 form.elements.pabrik.disabled=!perintah();form.elements.gudang.disabled=!perintah();
 form.elements.tujuan_lokasi.disabled=!(perintah()&&pk);
 if(bags){
  const n=Number(form.elements.karung_pk.value||0),c=Number(form.elements.curah_pk.value||0),total=Math.round(n*5000)+Math.round(c*100);
  form.elements.jumlah.value=String(total/100);
  let error='';if(!Number.isInteger(n)||n<0||c<0||!Number.isFinite(total)||total<=0)error='Isi jumlah karung dan curah lebih dari nol.';
  else if(total>Math.round(Number(selected.tersedia)*100))error='Jumlah melebihi stok bebas sumber.';
  form.elements.karung_pk.setCustomValidity(error);
 }
 weight();
}
function weight(){
 if(!selected)return;
 const n=Number(form.elements.jumlah.value||0);
 $('#tb-bobot').textContent=selected.jenis==='pk_giling'?'Total '+qty(n,'kg'):selected.seluruh?'Lot ini dipindahkan utuh sebelum digunakan dalam proses atau pengeluaran.':selected.satuan==='karung'?`Bobot mengikuti sumber: ${qty(n*Number(selected.berat_kg||0)/Number(selected.tersedia||1),'kg')}.`:'';
}
function choose(item){
 selected=item;pending=null;key=crypto.randomUUID().replaceAll('-','');
 $('#tb-pemilih').hidden=true;form.hidden=false;
 $('#tb-barang').textContent=item.label+' · '+item.kode;$('#tb-asal').textContent=loc(item.asal_lokasi);$('#tb-lokasi-asal').textContent=['pk_giling','pk_tumpukan'].includes(item.jenis)?'Tumpukan':'Area stok';$('#tb-pemilik').textContent=item.pemilik;$('#tb-bebas').textContent=qty(item.tersedia,item.satuan);
 $('#tb-jumlah-label').textContent='Jumlah '+(perintah()?'diperintahkan':'diminta')+' ('+item.satuan+')';
 const input=form.elements.jumlah;input.min=item.satuan==='kg'?'0.01':'1';input.step=item.satuan==='kg'?'0.01':'1';input.max=item.tersedia;input.value=item.seluruh?item.tersedia:'';input.readOnly=item.seluruh;
 if(item.jenis==='pk_giling'){const cents=Math.round(Number(item.tersedia)*100);form.elements.cara_pk.value='karung';form.elements.karung_pk.value=String(Math.floor(cents/5000));form.elements.curah_pk.value=String((cents%5000)/100)}
 factories();units();message('');
 if(!destinations().length){message('Belum ada tujuan aktif dalam perusahaan sumber yang sesuai gudang kerja. Periksa master atau pilih sumber lain.',true);$('#tb-simpan').disabled=true}else $('#tb-simpan').disabled=false;
 (item.jenis==='pk_giling'?form.elements.karung_pk:input).focus();
}
async function catalog(append=false){
 if(!root.isConnected)return;
 if(busy){if(!append)queued=true;return}busy=true;message('Memuat stok bebas…');$('#tb-lanjut').disabled=true;
 if(!append){position=0;list=[];$('#tb-sumber').replaceChildren()}
 try{
  const q=new URLSearchParams({jenis:search.elements.jenis.value,cari:search.elements.cari.value,posisi:String(position)});if(search.elements.gudang.value)q.set('gudang_id',search.elements.gudang.value);
  const d=await api('/sumber?'+q);if(!root.isConnected)return;warehouses=d.gudang;position=d.posisi;list.push(...d.items.filter(i=>perintah()||i.asal_id!==data().gudang_kerja?.gudang_id));
  const chosen=search.elements.gudang.value;search.elements.gudang.innerHTML='<option value="">Semua pabrik dan gudang</option>'+warehouses.map(w=>`<option value="${w.id}">${esc(loc(w))}</option>`).join('');search.elements.gudang.value=chosen;
  $('#tb-sumber').innerHTML=list.map((i,n)=>`<article class="tp-form-row"><h3>${esc(i.label)}</h3><p>${esc(i.kode)}</p><p class="tp-meta">${esc(loc(i.asal_lokasi))}<br>${esc(i.pemilik)} · ${esc(qty(i.tersedia,i.satuan))} bebas</p><button class="btn btn--kecil" type="button" data-tb-sumber="${n}">Pilih sumber ini</button></article>`).join('')||'<p class="bantu">Belum ada stok bebas yang cocok. Periksa filter atau sumber berikutnya.</p>';
  $('#tb-lanjut').hidden=!d.lanjut;message(list.length+' sumber tersedia.');
 }catch(e){message(e.message,true)}finally{busy=false;$('#tb-lanjut').disabled=false;if(queued){queued=false;catalog()}}
}
function open(mode){
 if(busy)return;
 if(mode==='perintah'&&!data().boleh_perintah||mode!=='perintah'&&(!data().gudang_kerja||data().admin))return;
 if(mode!==modeAktif){selected=null;pending=null}modeAktif=mode;
 $('#tb-judul').textContent=perintah()?'Perintah Transfer':'Permintaan ke gudang kerja';
 $('#tb-alur').textContent=perintah()?'Perintah langsung siap dilaksanakan operator asal. Stok tetap sampai pelaksanaan dicatat.':'Tujuan mengikuti gudang kerja. Admin menyetujui sebelum operator asal mencatat pelaksanaan.';
 $('#tb-simpan').textContent=pending?'Ulangi '+(perintah()?'perintah':'permintaan'):perintah()?'Terbitkan perintah':'Kirim permintaan';
 panel.showModal();
 if(selected){$('#tb-pemilih').hidden=true;form.hidden=false;return}
 form.hidden=true;$('#tb-pemilih').hidden=false;catalog();
}
const top=$('#tb-buka');if(top)top.onclick=()=>open('perintah');
$('#tp-minta-konteks').onclick=()=>open('permintaan');
function visibility(d){if(top)top.hidden=!d.boleh_perintah}
root.addEventListener('transfer-data',e=>visibility(e.detail));visibility(data());
$('#tb-lanjut').onclick=()=>catalog(true);search.onsubmit=e=>{e.preventDefault();catalog()};
form.elements.pabrik.onchange=warehouseOptions;form.elements.gudang.onchange=destinationLocation;form.elements.jumlah.oninput=weight;
form.elements.karung_pk.oninput=units;form.elements.curah_pk.oninput=units;
form.elements.cara_pk.onchange=()=>{if(form.elements.cara_pk.value==='karung'){const cents=Math.round(Number(form.elements.jumlah.value||0)*100);form.elements.karung_pk.value=String(Math.floor(cents/5000));form.elements.curah_pk.value=String((cents%5000)/100)}units()};
$('#tb-ganti').onclick=()=>{if(!busy&&!pending){form.hidden=true;$('#tb-pemilih').hidden=false;message('')}};
panel.addEventListener('click',e=>{const b=e.target.closest('[data-tb-sumber]');if(b&&!busy)choose(list[Number(b.dataset.tbSumber)]);if(e.target.closest('[data-tb-tutup]')&&!busy&&!pending)panel.close()});
panel.addEventListener('cancel',e=>{if(busy||pending)e.preventDefault()});
form.onsubmit=async e=>{
 e.preventDefault();if(busy||!selected)return;
 if(perintah()&&!data().boleh_perintah){message('Peran efektif berubah. Buka kembali formulir sesuai peran Anda.',true);return}
 const body=pending||{jenis:selected.jenis,sumber_id:selected.id,tujuan_id:Number(form.elements.gudang.value),jumlah:form.elements.jumlah.value,kunci:key,...(perintah()?{asal_id:selected.asal_id,tujuan:selected.jenis==='pk_giling'?form.elements.tujuan_lokasi.value:'gudang:'+form.elements.gudang.value}:{})};
 busy=true;form.querySelectorAll('input,select,button').forEach(x=>x.disabled=true);message('Menyimpan '+(perintah()?'perintah':'permintaan')+'…');
 try{await api(perintah()?'/perintah':'/permintaan',body);pending=null;selected=null;panel.close();root.dispatchEvent(new CustomEvent('transfer-perbarui',{detail:{pesan:perintah()?'Perintah siap dilaksanakan operator asal. Stok berubah saat pelaksanaan dicatat.':'Permintaan dikirim untuk persetujuan Admin.'}}))}
 catch(err){pending=err.pasti?null:body;message(err.message+(pending?' Isian dikunci. Ulangi pengiriman untuk memastikan dokumen yang sama.':' Isian tetap tersedia.'),true)}
 finally{busy=false;form.querySelectorAll('input,select,button').forEach(x=>x.disabled=!!pending);$('#tb-simpan').disabled=false;$('#tb-simpan').textContent=pending?'Ulangi '+(perintah()?'perintah':'permintaan'):perintah()?'Terbitkan perintah':'Kirim permintaan';if(!pending)units()}
};
})();
