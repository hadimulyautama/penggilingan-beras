(() => {
  const body=document.body,menus=[...document.querySelectorAll('.portal-menu,.portal-menu-bawah')],shade=document.querySelector('.portal-shade');
  function close(){body.classList.remove('sidebar-open');menus.forEach(menu=>menu.setAttribute('aria-expanded','false'));if(shade)shade.hidden=true;}
  let opener;
  menus.forEach(menu=>menu.addEventListener('click',()=>{opener=menu;const opened=body.classList.toggle('sidebar-open');menus.forEach(button=>button.setAttribute('aria-expanded',String(opened)));shade.hidden=!opened;if(opened)document.querySelector('.portal-sidebar a')?.focus();}));
  shade?.addEventListener('click',close);document.addEventListener('keydown',e=>{if(e.key==='Escape'){close();opener?.focus();}});
  document.querySelector('[data-theme-toggle]')?.addEventListener('click',e=>{const light=body.classList.toggle('terik');document.cookie=`produksi_terik=${light?'1':'0'}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol==='https:'?'; Secure':''}`;e.currentTarget.textContent=light?'☾':'☀';e.currentTarget.setAttribute('aria-label',light?'Aktifkan mode gelap':'Aktifkan mode terang');});
  document.querySelectorAll('[data-detail-keluar]').forEach(row=>{
    function open(){const target=new URL(row.dataset.detailKeluar,location.href);if(target.origin===location.origin&&/^\/pelanggan\/barang-keluar\/\d+$/.test(target.pathname))location.assign(target.href);}
    row.addEventListener('click',event=>{if(!event.target.closest('a,button,input,select,textarea'))open();});
    row.addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target===row){event.preventDefault();open();}});
  });
  // Native GET controls remain actual reads, usable without app action scripts.
  document.querySelectorAll('form[method=get] select').forEach(el=>el.addEventListener('change',()=>el.form.requestSubmit()));
  document.querySelectorAll('[data-pdf-share]').forEach(button=>button.addEventListener('click',async()=>{
    const status=document.getElementById('status-bagikan'),url=new URL(button.dataset.pdfShare,location.href).href;
    try{const response=await fetch(url,{credentials:'same-origin'});if(!response.ok)throw Error('PDF tidak tersedia.');const filename=(response.headers.get('content-disposition')||'').match(/filename="([^"]+)"/)?.[1]||'laporan.pdf';const file=new File([await response.blob()],filename,{type:'application/pdf'});
      if(navigator.canShare?.({files:[file]}))await navigator.share({files:[file]});else if(navigator.share)await navigator.share({url});else{await navigator.clipboard.writeText(url);if(status)status.textContent='Tautan laporan disalin. Penerima perlu masuk dengan akun yang berhak.';}
    }catch(error){if(error.name!=='AbortError'&&status)status.textContent='PDF belum berhasil dibagikan. Gunakan Unduh PDF.';}
  }));
})();
