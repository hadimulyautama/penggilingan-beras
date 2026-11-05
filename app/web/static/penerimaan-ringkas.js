/* Lembar penerimaan; POST tetap memakai endpoint operasional lama. */
(function () {
  'use strict';
  const root=document.querySelector('[data-penerimaan-ringkas]');
  if(!root||root.dataset.ready)return;root.dataset.ready='1';
  let data=JSON.parse(document.getElementById('penerimaan-awal').textContent);
  const host=root.querySelector('[data-formulir]'),error=root.querySelector('[data-galat]'),message=root.querySelector('[data-pesan]'),recovery=root.querySelector('[data-pemulihan]');
  const token=()=>document.getElementById('formulir-sesi')?.dataset.token||'';
  const storage='penerimaan-ringkas:'+root.dataset.actor+':'+root.dataset.tiket+':'+token();
  let state={forms:{},active:data.formulir[0]?.id||'',dirty:false,uncertain:false,inflight:false,key:crypto.randomUUID(),before:[],notice:''},busy=false,leaving=false,checked=null;
  const kg=v=>v==null?'Belum diketahui':Number(v).toLocaleString('id-ID',{maximumFractionDigits:3})+' kg';
  const ids=d=>d.catatan.map(c=>c.model+':'+c.id);
  function el(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;}
  function button(text,fn,primary=false){const b=el('button',text,'btn'+(primary?' btn--utama':''));b.type='button';b.onclick=fn;return b;}
  function notice(text,bad=false){const e=bad?error:message;e.textContent=text;e.hidden=false;}
  function persist(){try{sessionStorage.setItem(storage,JSON.stringify(state));return true;}catch(_){return false;}}
  function session(){if(window.SESIFORM&&!SESIFORM.periksa())throw Error('Sesi atau peran berubah. Buka kembali formulir dengan akun yang benar.');}
  async function call(url,body){session();const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),25000);try{
    const r=await fetch(url,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',signal:abort.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':token()},body:body?JSON.stringify(body):undefined});
    let j;try{j=await r.json();}catch(_){const e=Error('Balasan server belum lengkap.');e.status=r.status>=500?r.status:undefined;throw e;}
    if(!r.ok){const e=Error(typeof j.detail==='string'?j.detail:Array.isArray(j.detail)?j.detail.map(x=>(x.loc||[]).filter(v=>v!=='body').join('.')+': '+x.msg).join(' • '):'Pencatatan belum dapat dilakukan. Periksa status dan isian.');e.status=r.status;throw e;}return j;
  }finally{clearTimeout(timer);}}
  function selectField(field,values,value){const l=el('label',field.label),s=el('select');s.name=field.name;s.required=!!field.wajib;s.setAttribute('aria-label',field.label);s.append(new Option('Pilih '+(field.name==='tujuan'?'tujuan penerimaan':field.name==='warehouse_id'?'gudang penerima':'nilai'),''));
    for(const o of values){if(o.value==='')continue;const item=new Option(o.label+(o.alasan?' · '+o.alasan:''),o.value);item.disabled=!!o.alasan;s.append(item);}
    if(value&&!values.some(x=>String(x.value)===String(value)))s.append(new Option(value+' · pilihan sebelumnya, periksa ketersediaannya',value));
    s.value=value??'';s.onchange=()=>{state.forms[state.active][field.name]=s.value;state.dirty=true;if(field.name==='warehouse_id'){const tag=root.querySelector('[data-gudang-penerima-label]');if(tag)tag.textContent=(data.gudang_penerima.find(w=>String(w.value)===s.value)?.label||'Gudang dipilih saat penerimaan')+' · Barang Masuk';state.forms[state.active].tujuan='';persist();render();host.querySelector('[name=warehouse_id]')?.focus();}else persist();};l.append(s);return l;
  }
  function inputField(field,value){const l=el('label',field.label),inp=el(field.name==='alasan'?'textarea':'input');if(inp.tagName==='INPUT')inp.type=field.type==='number'?'number':'text';inp.name=field.name;inp.value=value??'';inp.setAttribute('aria-label',field.label);
    if(field.type==='number'){inp.step=field.name==='jumlah_karung'?'1':'any';inp.inputMode=field.name==='jumlah_karung'?'numeric':'decimal';}
    inp.oninput=()=>{state.forms[state.active][field.name]=inp.value;state.dirty=true;persist();};l.append(inp);return l;
  }
  function active(){return data.formulir.find(x=>x.id===state.active)||data.formulir[0];}
  function switchForm(id){if(busy||state.uncertain)return;state.active=id;persist();render();}
  function render(){host.replaceChildren();const a=active();
    recovery.hidden=!(state.uncertain||checked||state.inflight);
    if(!a||!data.pending){if(!data.catatan.length)host.append(el('p','Tindakan penerimaan mengikuti status tiket dan catatan terbaru.','bm-meta'));return;}
    if(!a.boleh){host.append(el('h2','Akses pencatatan'),el('p',a.alasan_akses||'Tindakan tidak diizinkan untuk peran efektif ini.'));return;}
    state.active=a.id;state.forms[a.id]??={};
    if(!state.forms[a.id].warehouse_id&&data.gudang_penerima?.length===1)state.forms[a.id].warehouse_id=String(data.gudang_penerima[0].value);
    const tag=root.querySelector('[data-gudang-penerima-label]');if(tag)tag.textContent=(data.gudang_penerima?.find(w=>String(w.value)===String(state.forms[a.id].warehouse_id))?.label||'Gudang dipilih saat penerimaan')+' · Barang Masuk';
    const f=el('form',null,'bm-form');f.append(el('h2',a.id==='gabah_masuk'?'Tentukan tujuan penerimaan':a.id==='tolak_pk_luar'?'Tolak PK luar':a.label.replace(/^\S+\s/,'')));
    f.append(el('p',data.tiket.kode+' · '+(data.tiket.nama_pelanggan||data.tiket.nama_supplier||data.tiket.pihak_nama||'Pihak belum tercatat'),'bm-meta'));
    for(const field of a.fields){if(!field.name||field.name==='timbangan_transaksi_id')continue;
      const value=state.forms[a.id][field.name];
      if(field.name==='warehouse_id')f.append(selectField(field,data.gudang_penerima||[],value));
      else if(field.name==='tujuan')f.append(selectField(field,data.tujuan.filter(x=>!x.warehouse_id||String(x.warehouse_id)===String(state.forms[a.id].warehouse_id)),value));
      else if(field.type==='select')f.append(selectField(field,(field.options||[]).map(x=>({value:x[0],label:x[1]})),value));
      else f.append(inputField(field,value));
    }
    if(a.id==='tolak_pk_luar')f.append(el('p','Penolakan memakai alasan dan penutupan tiket sesuai layanan lama. PK yang ditolak tidak menambah stok.','bm-meta'));
    else{f.append(el('p','Bobot penerimaan: '+kg(data.bobot_masuk.kg)+' · '+(data.bobot_masuk.sumber||'Sumber belum diketahui')+(data.bobot_masuk.sumber==='perkiraan'?' · Belum final':''),'bm-meta'));
      f.append(el('p',a.id==='gabah_masuk'?'Tujuan diperiksa lagi saat penyimpanan. Penerimaan dan penempatan tidak otomatis memulai proses.':a.id==='catat_pk_luar'?'Penerimaan ke tumpukan PK; pemindahan ke silo dan QC dilakukan terpisah.':'Produk, kemasan otomatis, tujuan stok, dan bobot mengikuti tiket serta layanan penerimaan.','bm-meta'));}
    const actions=el('div',null,'bm-aksi'),cancel=button('Tutup isian',()=>{host.hidden=true;const reopen=button('Lanjutkan isian penerimaan',()=>{host.hidden=false;reopen.remove();});host.after(reopen);persist();notice('Isian tetap tersimpan sementara di perangkat; belum mencatat penerimaan.');});
    const save=el('button',a.id==='gabah_masuk'?'Terima ke tujuan':a.id==='tolak_pk_luar'?'Tolak PK luar':'Catat penerimaan','btn btn--utama');save.type='submit';actions.append(cancel,save);f.append(actions);const refresh=button('Perbarui status & pilihan',()=>{state.before=ids(data);readStatus();});refresh.disabled=busy||state.uncertain;f.append(refresh);
    f.onsubmit=e=>{e.preventDefault();if(f.checkValidity())submit(a);};
    if(busy||state.uncertain||state.inflight)for(const e of f.querySelectorAll('input,select,textarea,button'))e.disabled=true;
    host.append(f);
    const other=data.formulir.find(x=>x.id!==a.id&&x.boleh);
    if(other){const fold=el('details');fold.append(el('summary',a.id==='tolak_pk_luar'?'Tetap menerima barang ini?':'Tidak menerima barang ini?'));const b=button(other.id==='tolak_pk_luar'?'Tolak PK luar':'Kembali ke penerimaan',()=>switchForm(other.id));b.disabled=busy||state.uncertain;fold.append(b);host.append(fold);}
  }
  function payload(a){const b={timbangan_transaksi_id:Number(root.dataset.tiket)},f=state.forms[a.id]||{};
    for(const x of a.fields){if(!x.name||x.name==='timbangan_transaksi_id')continue;const v=f[x.name];b[x.name]=v==null||v===''?null:x.type==='number'?Number(v):v;}
    if(['gabah_masuk','catat_pk_luar','tolak_pk_luar'].includes(a.id))b.kunci_kiriman=state.key;return b;
  }
  function detailUrl(){const u=new URL(location.href);u.searchParams.delete('buka');u.searchParams.delete('nilai');return u.pathname+u.search+u.hash;}
  function showCurrent(next){const box=root.querySelector('[data-status-rincian]');box.replaceChildren();box.append(el('p','Status terbaru: '+next.status_penerimaan+' · tiket '+(next.tiket.status_tiket||'Belum diketahui')));
    box.append(el('p','Bobot tiket: '+kg(next.tiket.berat_hpp_kg)+' · '+(next.tiket.sumber_berat||'Belum diketahui')));
    for(const c of next.catatan)box.append(el('p',c.kode+' · '+c.pemilik+' · '+kg(c.berat)+' · '+c.status));const a=active();if(a&&state.forms[a.id]){const draft=el('details');draft.append(el('summary','Isian perangkat yang dipertahankan'));for(const field of a.fields)if(field.name&&field.name!=='timbangan_transaksi_id')draft.append(el('p',field.label+': '+(state.forms[a.id][field.name]??'Belum diisi')));box.append(draft);}
  }
  async function readStatus(automatic=false,serverMessage=''){
    if(busy&&!automatic)return;if(!automatic){busy=true;render();}error.hidden=true;
    try{const next=await call('/api/actions/penerimaan-ringkas/'+root.dataset.tiket);if(!Array.isArray(next.catatan))throw Error('Data penerimaan terbaru belum lengkap.');
      const found=ids(next).some(x=>!state.before.includes(x));checked=next;showCurrent(next);data=next;state.inflight=false;state.uncertain=true;persist();
      const detail=root.querySelector('[data-status-detail]'),back=root.querySelector('[data-status-isian]');detail.hidden=!next.catatan.length;back.hidden=found||!next.pending;
      root.querySelector('[data-hasil-status]').textContent=found?'Catatan penerimaan terbaru ditemukan. Tidak ada pengiriman ulang. Baca detail dan riwayat untuk memastikan hasilnya.':next.catatan.length?'Catatan tiket sudah tersedia. Periksa detail sebelum mencoba tindakan lain.':'Belum ditemukan catatan baru pada pemeriksaan ini. Isian dan kunci kiriman dipertahankan. Pastikan status terbaru sebelum mencoba lagi.';
      if(automatic&&found){state={...state,forms:{},dirty:false,uncertain:false,inflight:false,key:crypto.randomUUID(),active:'',notice:/BELUM|Belum ditempatkan|⚠/.test(serverMessage)?serverMessage:''};persist();leaving=true;location.replace(detailUrl());}
    }catch(e){state.uncertain=true;state.inflight=false;persist();notice(automatic?'Server telah mengonfirmasi penyimpanan, tetapi rincian terbaru belum dapat dibaca. Jangan mengulang pencatatan. Baca status terbaru.':e.message,true);}
    finally{if(!automatic)busy=false;render();}
  }
  async function submit(a){if(busy||state.uncertain||!a.boleh)return;error.hidden=true;message.hidden=true;checked=null;
    const body=payload(a);if(a.id!=='tolak_pk_luar'&&!body.warehouse_id){notice('Pilih gudang penerima.',true);return;}state.before=ids(data);state.inflight=true;persist();busy=true;render();
    try{const out=await call(a.post,body);if(out.ok!==true)throw Error('Hasil pencatatan belum lengkap.');await readStatus(true,out.pesan||'');}
    catch(e){state.inflight=false;state.uncertain=!e.status||e.status>=500||e.status===409;
      notice(state.uncertain?'Status pencatatan perlu diperiksa. '+(e.status===409?e.message:'Balasan belum dapat dipastikan; isian dipertahankan. Jangan mengirim ulang sebelum membaca status terbaru.'):e.message,true);persist();}
    finally{busy=false;render();}
  }
  root.querySelector('[data-status-baca]').onclick=()=>readStatus();
  root.querySelector('[data-status-isian]').onclick=()=>{if(!checked||!data.pending)return;state.uncertain=false;state.inflight=false;checked=null;persist();render();notice('Data terbaru sudah dibaca. Isian tetap tersedia; periksa tujuan dan bobot sebelum menyimpan.');};
  root.querySelector('[data-status-detail]').onclick=()=>{state={...state,dirty:false,uncertain:false,inflight:false,forms:{},active:''};persist();leaving=true;};
  try{const saved=JSON.parse(sessionStorage.getItem(storage)||'null');if(saved){state={...state,...saved};if(state.inflight){state.inflight=false;state.uncertain=true;}if(state.dirty||state.uncertain)notice('Isian perangkat dipulihkan. Periksa data dan status sebelum menyimpan.');if(state.notice){notice(state.notice,true);state.notice='';persist();}}}catch(_){}
  const legacy=root.dataset.buka;if(data.formulir.some(a=>a.id===legacy))state.active=legacy;
  function markReturn(a){const u=new URL(a.href,location.href);if(u.origin===location.origin&&u.pathname+u.search===root.dataset.kembali){try{sessionStorage.setItem('barang-masuk-kembali:'+root.dataset.actor,root.dataset.kembali);}catch(_){}}}
  document.addEventListener('click',e=>{if(!root.isConnected||e.defaultPrevented||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(!a||a.target||a.hasAttribute('download')||a.getAttribute('href').startsWith('#'))return;
    if(a.hasAttribute('data-status-detail'))return;
    if(leaving||(!busy&&!state.dirty&&!state.uncertain)){markReturn(a);return;}
    e.preventDefault();e.stopImmediatePropagation();if(busy){notice('Permintaan sedang berlangsung. Tunggu hasil atau periksa status sebelum berpindah.',true);return;}
    root.querySelector('[data-nav-guard]')?.remove();const p=el('section',null,'terima-panel');p.dataset.navGuard='';const saved=persist();p.append(el('h2','Isian belum disimpan'),el('p',saved?'Isian tetap disimpan pada perangkat ini. Berpindah halaman tidak mencatat penerimaan atau stok.':'Perangkat belum dapat menyimpan isian. Tetap di halaman ini agar isian tidak hilang.'),button('Tetap di halaman ini',()=>p.remove()));if(saved)p.append(button('Lanjut dengan isian tersimpan',()=>{markReturn(a);leaving=true;location.assign(a.href);}));root.prepend(p);p.scrollIntoView({block:'start'});
  },true);
  window.addEventListener('beforeunload',e=>{if(root.isConnected&&!leaving&&(busy||state.dirty||state.uncertain)){persist();e.preventDefault();e.returnValue='';}});
  // Refresh QC saja: jangan render ulang host formulir atau menyalin snapshot
  // isian ke data transaksi. Draf dan fokus tetap pada simpul yang sama.
  let readBusy=false;
  const bolehBacaQC=()=>root.isConnected&&!busy&&!state.inflight&&!state.uncertain&&!checked;
  function withReadState(change){
    const view=window.KEADAAN_BACA.ambil(root);view.fields=[];
    // Baris tabel tanpa ID/tautan bisa berulang di timbang dan penilaian.
    // Jangan cocokkan TR: ke baris pertama; gunakan offset gulir tersimpan.
    if(view.anchor&&view.anchor.key.endsWith(':'))view.anchor=null;
    change();window.KEADAAN_BACA.pulihkan(root,view);
  }
  root.pfReadRefresh=async()=>{
    if(readBusy||!bolehBacaQC()||!window.KEADAAN_BACA)return false;
    const path=location.pathname+location.search,abort=new AbortController();
    const timer=setTimeout(()=>abort.abort(),25000);readBusy=true;
    try{
      session();
      const r=await fetch(path,{credentials:'same-origin',cache:'no-store',signal:abort.signal,headers:{'X-Pindah':'1'}});
      if(r.redirected||!r.ok)throw Error('Pembaruan QC belum dapat dibaca.');
      const doc=new DOMParser().parseFromString(await r.text(),'text/html'),fresh=doc.querySelector('[data-penerimaan-ringkas]');
      if(!bolehBacaQC()||path!==location.pathname+location.search)return false;
      session();
      if(!fresh||fresh.dataset.tiket!==root.dataset.tiket||fresh.dataset.actor!==root.dataset.actor)throw Error('Konteks penerimaan berubah.');
      const qc=root.querySelector('#terima-panel-qc'),next=fresh.querySelector('#terima-panel-qc');
      const status=root.querySelector('[data-qc-penerimaan-status]'),nextStatus=fresh.querySelector('[data-qc-penerimaan-status]');
      if(!qc||!next||!status||!nextStatus)throw Error('Rincian QC terbaru belum lengkap.');
      withReadState(()=>{window.KEADAAN_BACA.tukar(qc,next);window.KEADAAN_BACA.tukar(status,nextStatus);});
      return true;
    }catch(_){
      if(bolehBacaQC()&&path===location.pathname+location.search){
        withReadState(()=>{const note=root.querySelector('[data-qc-refresh-status]');if(note){note.textContent='Pembaruan QC belum dapat dibaca. Data sebelumnya tetap ditampilkan.';note.hidden=false;}});
      }
      return false;
    }finally{clearTimeout(timer);readBusy=false;}
  };
  function openFragment(){let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(_){return;}const target=document.getElementById(id);if(target&&root.contains(target))for(let n=target;n&&n!==root;n=n.parentElement)if(n.tagName==='DETAILS')n.open=true;}
  window.addEventListener('hashchange',openFragment);render();openFragment();
})();
