/* Pembacaan saja. Kartu, angka dan tautan tetap disusun renderer native. */
(function(){
 'use strict';
 const root=document.querySelector('[data-jasa-bertahap]');if(!root||root.dataset.ready)return;root.dataset.ready='1';
 const panel=root.querySelector('[data-jasa-baca-isi]'),status=root.querySelector('[data-jasa-baca-status]'),retry=root.querySelector('[data-jasa-baca-ulang]');
 const placeholder=panel.querySelector('.jasa-pelanggan--memuat').cloneNode(true);
 const address=location.pathname+location.search,session=document.getElementById('formulir-sesi')?.dataset.token||'',stamp=root.dataset.stamp;
 let sequence=0,controller=null;
 function current(n){return root.isConnected&&n===sequence&&location.pathname+location.search===address&&(document.getElementById('formulir-sesi')?.dataset.token||'')===session;}
 function stop(){++sequence;controller?.abort();controller=null;observer.disconnect();}
 const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
 function install(payload,n){
  if(!current(n))return;
  if(payload.stamp!==stamp)throw Error('Konteks sesi atau gudang berubah. Muat ulang halaman untuk membaca cakupan yang benar.');
  const doc=new DOMParser().parseFromString(payload.html,'text/html');
  if(doc.documentElement.dataset.versi!==document.documentElement.dataset.versi||doc.getElementById('formulir-sesi')?.dataset.token!==session)throw Error('Versi atau sesi berubah. Muat ulang halaman sebelum melanjutkan.');
  const list=doc.querySelector('.jasa-daftar'),count=list?.previousElementSibling;
  if(!list||!count?.matches('p.bantu'))throw Error('Struktur daftar belum dapat dibaca. Coba lagi.');
  const cards=list.querySelectorAll('a.jasa-pelanggan');
  if(!cards.length){
   list.replaceChildren();list.setAttribute('role','list');const article=placeholder.cloneNode(true);article.classList.remove('jasa-pelanggan--memuat');
   article.querySelector('h2').textContent=root.dataset.filtered==='1'?'Tidak ada pelanggan yang cocok dengan filter ini':'Belum ada pelanggan jasa';
   article.querySelector('[data-jasa-baca-pesan]').textContent=root.dataset.filtered==='1'?'Ubah nama atau status pesanan untuk melihat pelanggan lain.':'Pesanan baru tetap dibuat melalui alur Pos Timbang.';
   article.querySelectorAll('.jasa-angka strong').forEach(value=>value.textContent='—');list.append(article);
  }
  const next=list.nextElementSibling,fragment=document.createDocumentFragment();fragment.append(count.cloneNode(true),list.cloneNode(true));if(next?.matches('nav[aria-label="Halaman pelanggan"]'))fragment.append(next.cloneNode(true));
  if(!current(n))return;panel.replaceChildren(fragment);panel.setAttribute('aria-busy','false');status.textContent='Daftar pelanggan selesai dibaca.';
  root.querySelectorAll('[data-js-cetak]').forEach(b=>{b.disabled=false;b.removeAttribute('aria-describedby');});root.querySelector('#jasa-cetak-alasan').hidden=true;
 }
 async function read(){
  const n=++sequence;controller?.abort();controller=new AbortController();retry.hidden=true;status.textContent='Memuat pelanggan dan saldo…';panel.setAttribute('aria-busy','true');const message=panel.querySelector('[data-jasa-baca-pesan]');if(message)message.textContent='Memuat data. Filter tetap dapat digunakan.';
  try{
   const response=await fetch(root.dataset.url,{credentials:'same-origin',headers:{Accept:'application/json'},cache:'no-store',signal:controller.signal});
   if(!response.ok||response.redirected)throw Error(response.status===401||response.status===403?'Sesi atau izin berubah. Muat ulang halaman.':'Daftar belum dapat dibaca. Coba lagi hanya membaca data.');
   const payload=await response.json();install(payload,n);
  }catch(error){if(!current(n)||error.name==='AbortError')return;panel.setAttribute('aria-busy','false');status.textContent=error.message;const message=panel.querySelector('[data-jasa-baca-pesan]');if(message)message.textContent='Data belum tersedia. Gunakan Coba lagi untuk membaca tanpa mencatat transaksi.';retry.hidden=false;}
 }
 retry.addEventListener('click',read);
 if(window.PINDAH)PINDAH.pasang(window,'pagehide',stop);else window.addEventListener('pagehide',stop,{once:true});
 read();
})();
