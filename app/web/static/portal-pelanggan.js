(() => {
  const body=document.body,menu=document.getElementById('menu-pelanggan'),sidebar=document.querySelector('.portal-sidebar'),shade=document.querySelector('.portal-shade'),workspace=document.querySelector('.portal-workspace'),bottom=document.querySelector('.portal-bawah'),mobile=matchMedia('(max-width:900px)');
  function close(restore=false){
    body.classList.remove('sidebar-open');menu?.setAttribute('aria-expanded','false');if(shade)shade.hidden=true;
    if(sidebar){sidebar.inert=mobile.matches;sidebar.setAttribute('aria-hidden',String(mobile.matches));sidebar.removeAttribute('role');sidebar.removeAttribute('aria-modal');}
    if(workspace)workspace.inert=false;if(bottom)bottom.inert=false;
    if(restore&&mobile.matches)menu?.focus();
  }
  menu?.addEventListener('click',()=>{
    if(!mobile.matches||!sidebar)return;
    sidebar.inert=false;sidebar.setAttribute('aria-hidden','false');sidebar.setAttribute('role','dialog');sidebar.setAttribute('aria-modal','true');
    body.classList.add('sidebar-open');menu.setAttribute('aria-expanded','true');if(shade)shade.hidden=false;
    if(workspace)workspace.inert=true;if(bottom)bottom.inert=true;
    (sidebar.querySelector('a[aria-current=page]')||sidebar.querySelector('a[href]'))?.focus();
  });
  document.querySelector('.portal-tutup-menu')?.addEventListener('click',()=>close(true));
  shade?.addEventListener('click',()=>close(true));
  mobile.addEventListener('change',()=>close(Boolean(sidebar?.contains(document.activeElement))));
  document.addEventListener('keydown',e=>{
    if(!body.classList.contains('sidebar-open'))return;
    if(e.key==='Escape'){e.preventDefault();close(true);return;}
    if(e.key==='Tab'&&sidebar){
      const focusable=[...sidebar.querySelectorAll('a[href],button:not([disabled]),input:not([type=hidden]),select,textarea,summary')].filter(el=>el.getClientRects().length&&!el.closest('[hidden]')&&!el.closest('details:not([open]) > :not(summary)'));
      const first=focusable[0],last=focusable[focusable.length-1];
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
    }
  });
  close();
  document.querySelectorAll('[role=tablist]').forEach(list=>list.addEventListener('keydown',e=>{
    const tabs=[...list.querySelectorAll('a[role=tab][href]')],i=tabs.indexOf(e.target);
    if(i<0)return;
    if(e.key===' '){e.preventDefault();tabs[i].click();return;}
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
    e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
    tabs.forEach((tab,index)=>tab.tabIndex=index===n?0:-1);tabs[n].focus();
  }));
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
