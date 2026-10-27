/* Semua bobot, selisih, batas dan status berasal dari pratinjau server.
   Pembukaan halaman tidak pernah mengirim transaksi verifikasi. */
(function () {
  'use strict';
  var root=document.querySelector('[data-verifikasi-pengiriman]');
  if (!root || root.dataset.siap) return;
  root.dataset.siap='1';
  var data=JSON.parse(document.getElementById('verifikasi-awal').textContent);
  var isi=root.querySelector('[data-isi-verifikasi]'),galat=root.querySelector('[data-galat]');
  var kabar=root.querySelector('[data-kabar]'),refresh=root.querySelector('[data-terbaru]');
  var pilihan=null,tahap='daftar',catatan={},awal='',sibuk=false,basi=false,takPasti=false,rencana=null;
  function el(tag,teks,kelas) { var x=document.createElement(tag); if (teks!=null) x.textContent=teks; if(kelas)x.className=kelas; return x; }
  function btn(teks,fn,utama) { var b=el('button',teks,'btn'+(utama?' cm-utama':''));b.type='button';b.onclick=fn;return b; }
  function angka(n) { return Number(n).toLocaleString('id-ID',{maximumFractionDigits:6}); }
  function kg(n) { return n==null?'Belum tersedia':angka(n)+' kg'; }
  function key(d) { return d.kiriman_id?'k:'+d.kiriman_id:'p:'+d.perintah_id; }
  function sebab() { return catatan[key(pilihan)]||''; }
  function pair(w,k,v) { var d=el('div',null,'cm-pasang');d.append(el('span',k),el('strong',v));w.append(d); }
  function pesan(teks) { galat.textContent=teks;galat.hidden=false; }
  function identitas(d) {
    var box=el('div',null,'cm-konteks');box.append(el('strong',d.plat||'Armada belum dipilih'));
    box.append(el('span',d.tiket?d.tiket.kode+' · '+d.tiket.status_tiket:'Tanpa tiket yang dipilih'));
    box.append(el('span',d.jumlah_pelanggan+' pelanggan · '+d.jumlah_item+' barang · '+d.pelanggan_selesai+'/'+d.jumlah_pelanggan+' pelanggan selesai muat'));
    return box;
  }
  function status(d) {
    var box=el('section',null,'vv-status'+(!d.terverifikasi?' vv-status--hati':''));
    box.setAttribute('role','status');box.append(el('strong',d.status));
    if(d.halangan)box.append(el('span',d.halangan));
    if(d.catatan_otomatis)box.append(el('span','Pemeriksaan otomatis saat ini: '+d.catatan_otomatis));
    if(d.catatan_integrasi) {
      box.append(el('strong','Catatan percobaan integrasi tersimpan'));
      box.append(el('span',d.catatan_integrasi.pesan));
      if(d.catatan_integrasi.waktu)box.append(el('small',d.catatan_integrasi.waktu));
    }
    return box;
  }
  function pelanggan(d) {
    var box=el('section');box.append(el('h3','Muatan menurut catatan PadiFlow'));
    d.pelanggan.forEach(function(p,index) {
      var detail=el('details',null,'vv-customer');detail.open=index===0;
      var head=el('summary');head.append(el('strong',p.nama),el('span',kg(p.total_dimuat_kg)),el('small',p.kode+' · '+({perintah:'Belum selesai muat',dimuat:'Selesai muat',selesai:'Terverifikasi',batal:'Dibatalkan'}[p.status]||p.status)));
      detail.append(head);
      p.barang.forEach(function(i) {
        var row=el('section',null,'cm-barang');row.dataset.item=i.id;
        row.append(el('h3',i.nama_lengkap||i.nama),el('span',i.lokasi+' · '+i.pemilik,'cm-bantu'));
        var metrics=el('div',null,'cm-angka');
        [['Perintah',i.perintah],['Aktual',i.dimuat],[p.status==='perintah'?'Sisa perintah':'Tidak terkirim',i.sisa]].forEach(function(v) {
          var m=el('div');m.append(el('span',v[0]),el('strong',angka(v[1])+' '+i.satuan));metrics.append(m);
        });row.append(metrics);detail.append(row);
      });
      if(p.penutupan && p.penutupan.alasan) {
        detail.append(el('h3','Alasan barang tidak terkirim'),el('p',p.penutupan.alasan,'vv-reason'));
      }
      box.append(detail);
    });
    box.append(el('p','Subtotal pelanggan berasal dari catatan muatan PadiFlow. Satu hasil jembatan timbang berlaku untuk seluruh armada; selisih tidak dibagi ke pelanggan atau barang.','cm-bantu'));
    return box;
  }
  function tiket(d) {
    var box=el('section');box.append(el('h3','Hasil timbang satu armada'));
    var t=d.tiket;
    if(!t) { box.append(el('p','Tidak ada hasil tiket untuk dibandingkan. Verifikasi tanpa tiket mengikuti alur lama yang diizinkan.','cm-bantu'));return box; }
    pair(box,'Timbang pertama',kg(t.timbang1_kg));pair(box,'Timbang kedua',kg(t.timbang2_kg));
    pair(box,'Kendaraan kosong',kg(t.berat_kosong_kg));pair(box,'Kendaraan bermuatan',kg(t.berat_bermuatan_kg));
    pair(box,'Netto jembatan timbang',kg(t.netto_timbangan_kg));
    pair(box,'Tara karung · bagian total tersimpan',kg(t.tara_karung_kg));pair(box,'Tara lain',kg(t.tara_lain_kg));pair(box,'Total pengurang tara',kg(t.total_tara_kg));
    pair(box,'Berat barang setelah tara',kg(t.berat_barang_kg));
    if(t.kompatibilitas_netto)box.append(el('p','Snapshot berat barang belum tersedia pada tiket ini. Pembanding mengikuti netto tiket lama sebagai nilai kompatibilitas.','vv-reason'));
    var rincian=el('details'),head=el('summary','Rincian tara kemasan dari tiket');rincian.append(head);
    d.kemasan.forEach(function(b) {
      rincian.append(el('p',(b.catatan||b.jenis_kode||'Kemasan pada tiket')+' · '+angka(b.jumlah_karung)+' karung × '+angka(b.tara_per_karung_kg)+' kg/karung','vv-tara'));
    });
    if(!d.kemasan.length)rincian.append(el('p','Rincian kemasan tidak tersedia pada tiket ini.','cm-bantu'));
    rincian.append(el('p','Rincian berasal dari snapshot tiket. PadiFlow memakai hasil berat barang tersimpan dan tidak memotong tara lagi.','cm-bantu'));box.append(rincian);return box;
  }
  function perbandingan(d) {
    var box=el('section',null,'vv-total');box.append(el('h3','Pemeriksaan total kiriman'));
    pair(box,'Muatan aktual PadiFlow',kg(d.total_aktual_kg));
    pair(box,d.sumber_berat==='netto_kompatibilitas'?'Netto tiket lama · kompatibilitas':'Berat barang menurut tiket',kg(d.berat_tiket_kg));
    var diff=el('div',null,'vv-difference');pair(diff,'Selisih total',d.selisih_kg==null?'Belum tersedia':(d.selisih_kg>0?'+':'')+kg(d.selisih_kg));
    diff.append(el('p',d.selisih_kg==null?'Hasil tiket belum dapat dibandingkan.':d.selisih_kg===0?'Total sama.':d.selisih_kg>0?'Timbangan lebih berat daripada catatan muatan.':'Catatan muatan lebih berat daripada timbangan.','cm-bantu'));box.append(diff);return box;
  }
  function aturan(d) {
    var box=el('details');box.append(el('summary','Aturan pemeriksaan yang berlaku'));
    pair(box,'Batas otomatis','±'+kg(d.batas_otomatis_kg)+' · '+angka(d.otomatis_persen)+'%');
    pair(box,'Sebab manual wajib jika selisih >',kg(d.ambang_manual_kg));
    box.append(el('p','Ambang manual memakai nilai terbesar antara '+kg(d.manual_min_kg)+' dan '+angka(d.manual_persen)+'% muatan aktual.','cm-bantu'));
    return box;
  }
  function jejak(d) {
    var box=el('section');box.append(el('h3','Catatan verifikasi'));
    d.jejak.forEach(function(j) {
      var row=el('div',null,'cm-konteks');row.append(el('strong',j.kode));
      pair(row,'Metode',j.metode==='otomatis'?'Otomatis setelah timbang kedua':j.metode==='manual'?'Manual':'Tidak tercatat pada data lama');
      pair(row,'Pelaksana',j.pelaksana||'Tidak tercatat');pair(row,'Waktu',j.waktu||'Tidak tercatat');
      if(j.sebab_selisih)row.append(el('p','Sebab / catatan selisih timbang: '+j.sebab_selisih,'vv-reason'));
      box.append(row);
    });
    if(sebab().trim() && !d.jejak.some(function(j){return j.sebab_selisih===sebab().trim();}))
      box.append(el('h3','Catatan yang sempat Anda isi'),el('p',sebab(),'vv-reason'));
    return box;
  }
  function daftar() {
    if(!data.length)isi.append(el('p','Tidak ada kiriman menunggu verifikasi.'));
    data.forEach(function(d) {
      var box=el('section',null,'cm-pelanggan');box.append(identitas(d),status(d),perbandingan(d));
      var b=btn(d.terverifikasi?'Lihat hasil verifikasi':'Periksa kiriman',function(){buka(d);});b.disabled=basi||takPasti;box.append(b);isi.append(box);
    });
  }
  function buka(d) {
    pilihan=d;if(catatan[key(d)]==null)catatan[key(d)]='';awal=sebab();
    tahap=d.terverifikasi?'hasil':'form';rencana=null;galat.hidden=true;refresh.hidden=false;gambar();
  }
  function kembali() {
    if(sibuk)return;
    if(tahap==='review') { tahap='form';rencana=null;gambar();return; }
    if(!pilihan.terverifikasi && sebab()!==awal) {
      var q=el('section',null,'cm-periksa');q.append(el('strong','Catatan belum disimpan'),el('p','Kembali tanpa memverifikasi kiriman?'));
      var a=el('div',null,'cm-tindakan');a.append(btn('Tetap isi',function(){q.remove();}),btn('Buang & kembali',function(){catatan[key(pilihan)]='';pilihan=null;tahap='daftar';gambar();}));q.append(a);isi.prepend(q);return;
    }
    pilihan=null;tahap='daftar';rencana=null;gambar();
  }
  function form() {
    var d=pilihan,box=el('section',null,'cm-form');
    box.append(el('h2',d.terverifikasi?'Hasil verifikasi pengiriman':tahap==='review'?'Konfirmasi verifikasi manual':'Pemeriksaan verifikasi'),identitas(d),status(d));
    var layout=el('div',null,'vv-layout'),fields=el('div'),side=el('aside',null,'vv-side');
    fields.append(tiket(d),pelanggan(d));side.append(perbandingan(d),aturan(d),el('p','Verifikasi mengubah status seluruh kiriman. Jumlah muatan dan stok tidak dipotong lagi.','cm-bantu'));
    if(d.terverifikasi)fields.append(jejak(d));
    else if(tahap==='review') {
      fields.append(el('h3','Sebab / catatan pemeriksaan'),el('p',sebab().trim()||'Tidak ada catatan.','vv-reason'));
      fields.append(el('p','Seluruh '+d.jumlah_pelanggan+' pelanggan dalam kiriman ini akan diverifikasi bersama. Jumlah barang dan saldo stok tetap.','cm-bantu'));
      d.pelanggan.filter(function(p){return p.status!=='batal';}).forEach(function(p){fields.append(el('p',p.nama+' · '+p.kode));});
    } else {
      var label=el('label',d.sebab_wajib?'Sebab selisih besar · wajib':'Catatan pemeriksaan · opsional');label.htmlFor='vv-sebab';
      var input=el('textarea');input.id='vv-sebab';input.rows=3;input.maxLength=300;input.value=sebab();input.setAttribute('aria-required',d.sebab_wajib?'true':'false');
      input.oninput=function(){catatan[key(d)]=input.value;rencana=null;if(!basi&&!takPasti)galat.hidden=true;};
      fields.append(label,input,el('p','Sebab selisih timbang terpisah dari alasan barang tidak terkirim yang dicatat saat Selesai muat.','cm-bantu'));
    }
    layout.append(fields,side);box.append(layout);
    var actions=el('div',null,'cm-tindakan');actions.append(btn(tahap==='review'?'Kembali periksa':'Kembali',kembali));
    if(!d.terverifikasi) {
      var b=btn(tahap==='review'?'Verifikasi seluruh kiriman':'Periksa verifikasi manual',tahap==='review'?simpan:periksa,true);
      b.dataset.konfirmasi='';b.disabled=!d.boleh_manual||basi||takPasti;actions.append(b);
    }
    var a=el('a','Lihat detail dan riwayat pengiriman','btn');a.href='/barang-keluar/'+d.perintah_id;actions.append(a);
    box.append(actions);isi.append(box);
  }
  function gambar() { isi.replaceChildren();if(pilihan)form();else daftar(); }
  function payload() { return {perintah:String(pilihan.perintah_id),tiket:pilihan.tiket?String(pilihan.tiket.id):null,
    kiriman_id:pilihan.kiriman_id,perintah_ids:pilihan.perintah_ids,dasar:pilihan.dasar,sebab_selisih:sebab()}; }
  function kunci(v) {
    sibuk=v;root.querySelectorAll('button,textarea').forEach(function(e){
      if(v){e.dataset.sebelumKunci=e.disabled?'1':'0';e.disabled=true;}
      else if(e.dataset.sebelumKunci!=null){e.disabled=e.dataset.sebelumKunci==='1';delete e.dataset.sebelumKunci;}
    });
    if(!v&&pilihan){var b=isi.querySelector('[data-konfirmasi]');if(b)b.disabled=!pilihan.boleh_manual||basi||takPasti;}
  }
  async function panggil(url,method,body) {
    if(window.SESIFORM&&!SESIFORM.periksa())throw Error('Sesi berubah. Catatan tetap tersedia; gunakan akun pembuka formulir.');
    var tag=document.getElementById('formulir-sesi'),ctrl=new AbortController(),timeout=setTimeout(function(){ctrl.abort();},20000);
    try {
      var r=await fetch(url,{method:method,credentials:'same-origin',signal:ctrl.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':tag?tag.dataset.token:''},body:body?JSON.stringify(body):undefined});
      var j=await r.json().catch(function(){return {};});
      if(window.SESIFORM&&!SESIFORM.periksa())throw Error('Sesi berubah; periksa status terbaru sebelum mengulang.');
      if(!r.ok){var e=Error(typeof j.detail==='string'?j.detail:'Permintaan belum dapat diproses. Catatan tetap tersedia.');e.status=r.status;throw e;}return j;
    }finally{clearTimeout(timeout);}
  }
  async function ambil() {
    var j=await panggil('/api/actions/pratinjau-muat?tujuan=verifikasi&perintah='+encodeURIComponent(pilihan.perintah_id),'GET');
    if(!j.dasar||!Array.isArray(j.pelanggan)||j.perintah_id!==pilihan.perintah_id)throw Error('Ringkasan pemeriksaan belum lengkap.');return j;
  }
  async function periksa() {
    if(sibuk||basi||takPasti||!pilihan||!pilihan.boleh_manual||pilihan.terverifikasi)return;
    if(pilihan.sebab_wajib&&!sebab().trim()){pesan('Tuliskan sebab selisih besar. Spasi kosong tidak dianggap sebagai sebab.');return;}
    kunci(true);
    try {
      var j=await ambil();
      if(j.dasar!==pilihan.dasar){basi=true;pesan('Data pemeriksaan berubah. Catatan tetap tersedia; periksa data terbaru lalu konfirmasi ulang.');return;}
      if(!j.boleh_manual)throw Error(j.halangan||'Kiriman belum dapat diverifikasi manual.');
      rencana=j;tahap='review';galat.hidden=true;gambar();
    }catch(e){pesan(e.message);if(e.status===409)basi=true;}
    finally{kunci(false);}
  }
  async function terbaru(tersimpan) {
    if(sibuk&&!tersimpan||!pilihan)return;
    if(!tersimpan)kunci(true);
    try {
      var j=await ambil();var index=data.findIndex(function(d){return key(d)===key(pilihan);});if(index>=0)data[index]=j;
      pilihan=j;rencana=null;basi=false;takPasti=false;tahap=j.terverifikasi?'hasil':'form';galat.hidden=true;
      if(!tersimpan){kabar.textContent='Data terbaru dimuat. Catatan tetap tersedia; baca ringkasan sebelum konfirmasi ulang.';kabar.hidden=false;}
      gambar();
    }catch(e){basi=true;pesan(tersimpan?'Verifikasi sudah dikonfirmasi server, tetapi ringkasan belum dapat dimuat. Periksa status atau riwayat sebelum tindakan berikutnya.':e.message);}
    finally{if(!tersimpan)kunci(false);}
  }
  async function simpan() {
    if(sibuk||!rencana||basi||takPasti||!pilihan.boleh_manual||pilihan.terverifikasi)return;
    kunci(true);galat.hidden=true;
    try {
      var j=await panggil('/api/actions/verifikasi-keluar','POST',payload());
      if(j.ok!==true)throw Error('Balasan verifikasi belum lengkap.');
      kabar.textContent=j.pesan||'Seluruh kiriman terverifikasi.';kabar.hidden=false;await terbaru(true);
    }catch(e){takPasti=!e.status||e.status>=500;basi=e.status===409;rencana=null;tahap='form';pesan(takPasti?'Status verifikasi belum dapat dipastikan. Catatan tetap tersedia. Periksa status kiriman atau riwayat sebelum mengulang.':e.message);gambar();}
    finally{kunci(false);}
  }
  refresh.onclick=function(){terbaru(false);};gambar();if(data.length===1)buka(data[0]);
})();
