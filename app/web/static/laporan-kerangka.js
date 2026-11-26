/* Kontrol GET laporan saja. Pembaca, angka dan PDF tetap native. */
(function(){
 'use strict';
 function mulai(){
  const root=document.querySelector('[data-laporan-shell]');if(!root||root.dataset.lpReady)return;root.dataset.lpReady='1';
  const form=root.querySelector('form'),period=form.elements.periode,range=form.querySelector('.lp-rentang'),apply=form.querySelector('.lp-tampilkan');
  root.querySelector('[data-lp-proses]').addEventListener('change',event=>{form.action=event.target.value;form.requestSubmit();});
  period.addEventListener('change',()=>{const custom=period.value==='khusus';range.hidden=!custom;apply.hidden=!custom;range.querySelectorAll('input').forEach(el=>{el.disabled=!custom;el.required=custom;});if(!custom)form.requestSubmit();});
  range.querySelectorAll('input').forEach(el=>el.addEventListener('input',()=>form.elements.sampai.setCustomValidity('')));
  form.addEventListener('submit',event=>{
   const last=form.elements.sampai;last.setCustomValidity('');
   if(period.value==='khusus'&&form.elements.dari.value>last.value){event.preventDefault();last.setCustomValidity('Tanggal akhir harus sama atau setelah tanggal awal.');last.reportValidity();return;}
   if(event.defaultPrevented||!window.PINDAH)return;
   const target=new URL(form.action,location.href);if(target.origin!==location.origin||!Array.from(root.querySelector('[data-lp-proses]').options).some(o=>o.value===target.pathname))return;
   target.search=new URLSearchParams(new FormData(form)).toString();event.preventDefault();
   const a=document.createElement('a');a.href=target.pathname+target.search;a.hidden=true;root.append(a);a.click();a.remove();
  });
  const guide=root.querySelector('#lp-panduan');root.querySelector('[data-lp-panduan]').addEventListener('click',()=>guide.showModal());root.querySelector('[data-lp-tutup]').addEventListener('click',()=>guide.close());
 }
 function siapkan(root,content){
  const fresh=content.querySelector('[data-laporan-detail]'),dataNode=content.querySelector('#laporan-data');
  const code=root.dataset.laporanShell,form=root.querySelector('form'),nextForm=fresh?.querySelector('form');
  if(!fresh||!dataNode||!nextForm||nextForm.method!=='get'||nextForm.getAttribute('action')!=='/laporan/'+code||!root.querySelector('table')||!fresh.querySelector('#lp-panduan'))throw Error('Struktur laporan berubah. Muat ulang halaman.');
  const data=JSON.parse(dataNode.textContent);
  if(data.kode!==code||!['ringkasan','rincian','kolom','kepala_tabel','catatan'].every(k=>Array.isArray(data[k]))||!data.kolom.length||window.PadiLaporanRenderer?.versi!==1)throw Error('Isi laporan belum lengkap. Coba lagi.');
  const cap=document.documentElement.dataset.versi,expected=['laporan-periode-detail.js','menu-layar.js','kerangka-langsung.js','navigasi-daftar-bertahap.js'].map(n=>'/static/'+n+'?v='+cap).sort();
  if(JSON.stringify(Array.from(content.querySelectorAll('script:not([type="application/json"])'),s=>s.getAttribute('src')).sort())!==JSON.stringify(expected))throw Error('Kontrol laporan berubah. Muat ulang halaman.');
  const pdf=Array.from(fresh.querySelectorAll('.lp-panel-aksi a'));
  if(pdf.length!==2||pdf.some(a=>{const u=new URL(a.getAttribute('href'),location.href);return u.origin!==location.origin||u.pathname!=='/laporan-periode/'+code+'.pdf';}))throw Error('Dokumen laporan belum sesuai. Coba lagi.');
  const rendered=document.createElement('div');rendered.innerHTML=PadiLaporanRenderer.tabel(data);
  return {root,fresh,form,nextForm,data,rendered,pdf};
 }
 function isi(p){
  const {root,data,rendered,form,nextForm}=p,body=root.querySelector('#lap-isi'),wrap=body.querySelector('.lp-tabel'),table=wrap.querySelector('table'),next=rendered.querySelector('.lp-tabel table');
  if(next){
   if(table.tHead.innerHTML!==next.tHead.innerHTML)table.tHead.replaceChildren(...Array.from(next.tHead.childNodes));
   table.tBodies[0].replaceChildren(...Array.from(next.tBodies[0].childNodes));next.closest('.lp-tabel').replaceWith(wrap);
  }else{
   const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=data.kolom.length;cell.textContent='Tidak ada transaksi pada periode ini.';row.append(cell);table.tBodies[0].replaceChildren(row);
   for(const node of rendered.querySelectorAll('p'))if(node.textContent==='Tidak ada transaksi pada periode ini.')node.remove();
   rendered.querySelector('.lp-ringkasan').after(wrap);
  }
  body.replaceChildren(...Array.from(rendered.childNodes));body.setAttribute('aria-busy','false');
  for(const key of ['dari','sampai'])form.elements[key].value=nextForm.elements[key].value;
  const links=root.querySelectorAll('.lp-panel-aksi a');links.forEach((a,i)=>{for(const attr of Array.from(a.attributes))a.removeAttribute(attr.name);for(const attr of p.pdf[i].attributes)a.setAttribute(attr.name,attr.value);});
  root.querySelector('.halaman-bertahap__status').remove();root.querySelector('[data-shell-message]').remove();
  delete root.dataset.halamanBertahap;delete root.dataset.ready;root.dataset.halamanIsi='laporan-'+root.dataset.laporanShell;return root;
 }
 window.PadiLaporanFrame={versi:1,siapkan,isi};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mulai,{once:true});else mulai();
})();
