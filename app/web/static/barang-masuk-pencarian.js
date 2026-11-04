/* Hanya Cari/Enter atau perubahan filter yang DIKONFIRMASI mengirim GET.
 * Kegagalan baca mempertahankan formulir dan hasil sebelumnya. */
(function(){'use strict';
 function pasang(root){if(!root||root.dataset.siap)return;root.dataset.siap='1';let busy=false,lastURL='',lastDraft=[];
  const search=root.querySelector('[data-bm-search]'),input=search.querySelector('[name=cari]'),name=search.querySelector('[name=pemasok]');
  const originalName=root.dataset.pemasokTertampil;
  function changed(){root.querySelector('#bm-belum-cari').hidden=input.value.trim()===root.dataset.cariTertampil&&name.value===originalName;}
  search.addEventListener('input',changed);search.addEventListener('change',changed);
  search.addEventListener('pf:read-state-restored',changed);
  async function baca(url){if(busy)return;busy=true;lastURL=url;lastDraft=[input.value,name.value];root.setAttribute('aria-busy','true');root.querySelectorAll('button').forEach(b=>b.disabled=true);
   const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
   try{const r=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{'X-Barang-Masuk-Cari':'1'},signal:controller.signal});
    if(r.redirected||!r.ok)throw new Error('baca');const doc=new DOMParser().parseFromString(await r.text(),'text/html'),next=doc.querySelector('[data-bm-page]');
    if(!next||next.querySelector('[data-bm-error]:not([hidden])'))throw new Error('baca');
    if(!root.isConnected)return;const requested=new URL(url,location.href);
    if((requested.searchParams.get('cari')||'')!==input.value.trim())next.querySelector('[name=cari][type=search]').value=input.value;
    if((requested.searchParams.get('pemasok')||'')!==name.value){const dest=next.querySelector('[data-bm-search] [name=pemasok]');if(!Array.from(dest.options).some(o=>o.value===name.value))dest.add(new Option(name.value,name.value));dest.value=name.value;}
    root.replaceWith(next);history.pushState({pindah:1},'',url);if(window.PINDAH){PINDAH.lupakan();PINDAH.lupakanSentuhan();}pasang(next);
    next.querySelector('.bm-jumlah').setAttribute('tabindex','-1');next.querySelector('.bm-jumlah').focus({preventScroll:true});
   }catch(_){if(root.isConnected){root.querySelector('[data-bm-error]').hidden=false;changed();}}
   finally{clearTimeout(timer);busy=false;root.removeAttribute('aria-busy');root.querySelectorAll('button').forEach(b=>b.disabled=false);}
  }
  root.querySelectorAll('[data-bm-form]').forEach(f=>f.addEventListener('submit',e=>{e.preventDefault();const url=new URL(f.action,location.href);url.search=new URLSearchParams(new FormData(f)).toString();baca(url.pathname+url.search);}));
  root.addEventListener('click',e=>{const a=e.target.closest('[data-bm-nav] a');if(a&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.altKey&&e.button===0){e.preventDefault();e.stopPropagation();baca(a.pathname+a.search);}});
  changed();
  root.querySelector('[data-bm-retry]').addEventListener('click',()=>{if(lastURL&&input.value===lastDraft[0]&&name.value===lastDraft[1])baca(lastURL);else search.requestSubmit();});
 }
 pasang(document.querySelector('[data-bm-page]'));
})();
