/* Halaman laporan menggunakan data dan periode yang sama dengan PDF. */
(function(){'use strict';const root=document.querySelector('[data-laporan-detail]');if(!root||root.dataset.siap)return;root.dataset.siap='1';
  function aman(s) { var el = document.createElement("span"); el.textContent = String(s); return el.innerHTML; }
  function tabel(d) {
    var h = '<p class="lp-catatan">Periode: ' + aman(d.periode) + ' · WIB</p>' +
      '<p class="lp-catatan">Dasar: ' + aman(d.dasar) + '</p><div class="lp-ringkasan">';
    (d.ringkasan_kelompok || [{nama:'Ringkasan',rincian:d.ringkasan}]).forEach(function (g) {
      var jenis = g.nama === 'Aktivitas' ? ' lp-kelompok--aktivitas' : g.nama === 'Hasil' ? ' lp-kelompok--hasil' : '';
      h += '<section class="lp-kelompok' + jenis + '"><h3>' + aman(g.nama) + '</h3><div class="lp-bagian-metrik">';
      var bagian = null;
      g.rincian.forEach(function (r) {
        if ((r.bagian || null) !== bagian) {
          if (bagian) h += '</dl></div>';
          bagian = r.bagian || null;
          if (bagian) h += '<div class="lp-subkelompok"><h4>' + aman(bagian) + '</h4><dl>';
        }
        var metrik = '<dt>' + aman(r.nama) + '</dt><dd>' + aman(r.nilai) + (r.persen_bahan ? '<small class="lp-persen">' + aman(r.persen_bahan) + (r.persen_bahan.endsWith('%') ? ' bahan baku' : '') + '</small>' : '') + '</dd>';
        var kelas = 'lp-metrik' + (r.nama.indexOf('Total ') === 0 ? ' lp-total' : '');
        h += bagian ? '<div class="' + kelas + '">' + metrik + '</div>' : '<dl class="' + kelas + '">' + metrik + '</dl>';
      });
      if (bagian) h += '</dl></div>';
      h += '</div></section>';
    });
    h += '</div>';
    if (d.rincian.length) {
      var kolommen = d.kolom.map(function (c) { return [c.kunci,c.nama,c.kelompok,c.subkelompok]; });
      h += '<div class="lp-tabel"><table><caption class="lbl">Rincian transaksi</caption><thead>';
      d.kepala_tabel.forEach(function (row) {
        h += '<tr>';
        row.forEach(function (c) {
          h += '<th scope="' + (c.kolom > 1 ? 'colgroup' : 'col') + '" colspan="' + c.kolom + '" rowspan="' + c.baris + '">' + aman(c.nama) + '</th>';
        });
        h += '</tr>';
      });
      h += '</thead><tbody>';
      d.rincian.forEach(function (r) {
        h += r.belum_selesai ? '<tr class="lp-belum-selesai" aria-label="' + aman(r.kode).replace(/"/g, '&quot;') + ', belum selesai">' : '<tr>';
        kolommen.forEach(function (c) {
          var nilai = r[c[0]] == null ? 'Belum tercatat' : r[c[0]];
          if (c[0] === "kode" && r.tiket !== "-") nilai += " / " + r.tiket;
          h += '<td data-label="' + aman([c[2],c[3],c[1]].filter(Boolean).join(' · ')).replace(/"/g, '&quot;') + '">' + aman(nilai) +
            (c[0] === "kode" ? '<small class="lp-tanggal">' + aman(r.tanggal) + '</small>' : '') +
            (c[0] === "nota" && r.sumber_nota === "Mengikuti timbangan" ? '<small class="lp-catatan">Mengikuti timbangan</small>' : '') + '</td>';
        });
        h += '</tr>';
      });
      h += '</tbody></table></div>';
    } else { h += '<p>Tidak ada transaksi pada periode ini.</p>'; }
    h += '<h3 class="lbl">Keterangan</h3>';
    d.catatan.forEach(function (c) { h += '<p class="lp-catatan">' + aman(c) + '</p>'; });
    return h;
  }

const data=JSON.parse(document.getElementById('laporan-data').textContent);root.querySelector('#lap-isi').innerHTML=tabel(data);
const form=root.querySelector('form'),periode=form.elements.periode,rentang=form.querySelector('.lp-rentang'),tampilkan=form.querySelector('.lp-tampilkan');
root.querySelector('[data-lp-proses]').addEventListener('change',e=>{form.action=e.target.value;form.requestSubmit();});
periode.addEventListener('change',()=>{const khusus=periode.value==='khusus';rentang.hidden=!khusus;tampilkan.hidden=!khusus;rentang.querySelectorAll('input').forEach(el=>{el.disabled=!khusus;el.required=khusus;});if(!khusus)form.requestSubmit();});
form.addEventListener('submit',e=>{const awal=form.elements.dari,akhir=form.elements.sampai;akhir.setCustomValidity('');if(periode.value==='khusus'&&awal.value>akhir.value){e.preventDefault();akhir.setCustomValidity('Tanggal akhir harus sama atau setelah tanggal awal.');akhir.reportValidity();}});
rentang.querySelectorAll('input').forEach(el=>el.addEventListener('input',()=>form.elements.sampai.setCustomValidity('')));
const panduan=root.querySelector('#lp-panduan');root.querySelector('[data-lp-panduan]').addEventListener('click',()=>panduan.showModal());root.querySelector('[data-lp-tutup]').addEventListener('click',()=>panduan.close());
})();
