# Tampilan Panduan bersama

`hmu_tampilan/static/panduan.css` adalah satu sumber gaya Panduan. Jangan menyalin aturan panel, judul, tombol tutup, jarak teks, atau tab langkah ke CSS halaman. Warna mengikuti tema aplikasi.

Untuk panduan halaman baru, gunakan kerangka yang sama dan isi khusus halaman:

```jinja
{% from '_panduan.html' import panel %}
{% call panel('panduan-halaman', 'Panduan halaman', penutup={'data-halaman-tutup': ''}) %}
  <p>Penjelasan khusus halaman ini.</p>
{% endcall %}
```

Pemanggil tetap membuka dialog dengan `showModal()`, mengikat tombol tutup, dan mengembalikan fokus. Atribut tambahan pada dialog dapat diberikan melalui `atribut={...}`. ID harus unik. Makro menghasilkan judul, ikon informasi, tombol tutup dan `.pd-panduan__isi` yang sama untuk semua halaman; teks tidak disatukan.

Untuk panduan bertahap, gunakan `.pd-panduan__tahap` pada kelompok tombol, `.pd-panduan__panel` pada setiap isi langkah, dan `.pd-panduan__tambahan` untuk penjelasan tambahan. Pertahankan hubungan ARIA tab-panel serta navigasi keyboard. Panduan Barang Keluar adalah contoh pemakaiannya.

Panel yang dibentuk lewat JavaScript menggunakan `.pd-panduan`, `.pd-panduan__kepala`, `.pd-panduan__tutup`, dan `.pd-panduan__isi` yang sama; tidak memiliki salinan aturan gaya sendiri.

Saat ini dipakai oleh Barang Keluar, Barang Masuk, Pekerjaan, Stok, Riwayat Kepemilikan dan Pengalihan PK. Panduan di layar lain dapat memakai makro yang sama tanpa mengubah isi atau izin tindakan.
