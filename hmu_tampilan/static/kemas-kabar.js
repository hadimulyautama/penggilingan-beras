/* Notifikasi sekali setelah server memastikan kemas ulang tersimpan. */
(function(){
  if(location.hash!=='#kemas-ulang-berhasil')return;
  history.replaceState(history.state,'',location.pathname+location.search);
  var t=document.getElementById('kabar');if(!t)return;
  var utama=document.createElement('div');utama.className='kabar__utama';
  var ikon=document.createElement('span');ikon.className='kabar__ikon';ikon.setAttribute('aria-hidden','true');ikon.textContent='✓';
  var teks=document.createElement('span');teks.className='kabar__teks';teks.textContent='Kemas ulang berhasil. Stok sudah diperbarui.';
  utama.append(ikon,teks);t.replaceChildren(utama);t.className='kabar kabar--ok';t.style.display='block';
  function tutup(){t.style.display='none';}t.onclick=tutup;setTimeout(tutup,6000);
})();
