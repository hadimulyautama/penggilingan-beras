# Perapian tiga bagian detail Pengiriman & Retur

Baseline main fbc357e. Cakupan hanya penyajian; layanan, controller, model, endpoint, formulir dan rumus tidak diubah.

1. Kepala: navigasi modul dipindahkan ke dalam kontainer detail pengiriman agar tidak mendapat tambahan gap dari flex halaman. Tautan kembali, jarak menuju kepala dan ukuran judul disamakan. Pengajuan menonjolkan “Pengajuan retur #…”; kode pengiriman tetap sebagai referensi asal. Navigasi modul pada penerimaan disamakan dengan pengajuan, tautan asal tetap ada.
2. Kartu/fakta: label penerimaan memakai huruf biasa dan ukuran yang konsisten. Fakta tetap lengkap. Kartu Data timbang saat penerimaan dipisah dari Data tiket saat ini; masing-masing tetap mengambil objek snapshot/objek tiket lama. Tidak ada penggantian sumber atau nilai.
3. Riwayat: macro format baca mengubah string angka JSON ke format Indonesia dan menampilkan Belum tersedia untuk None/Undefined/string kosong. Nol tetap nol, nilai negatif tetap bertanda. Bobot memakai macro kg_rinci aplikasi; tara mempertahankan empat desimal sehingga 0,0001 tidak menjadi nol. Snapshot audit asli tidak ditulis ulang.

## Berkas

- Template: pengiriman.html, _pengiriman_detail_tab.html, retur_asal.html, retur_detail.html, _detail_kirim_tabs.html.
- CSS khusus: detail_kirim_retur.css (cache URL v2).
- Tes: test_detail_pengiriman_retur.py (assert identitas, format dan pemisahan snapshot), test_detail_kirim_format.py (sembilan kasus batas).
- Dokumen ini. JavaScript, seluruh layanan dan controller tetap sama dengan baseline.

## Bukti uji

- 185 tes PostgreSQL: seluruh barang keluar, pengajuan/penerimaan retur dan detail. Lulus; stok, toleransi inklusif, manual melekat, transaksi bersamaan, pemilik/gudang, koreksi, idempotensi dan akses memakai layanan asli.
- 800 tes non-PostgreSQL lulus, termasuk sembilan kasus format: angka/string, negatif, nol, None, string None/kosong, Undefined, tara kecil empat desimal.
- Lima tes detail final lulus lagi: judul pengajuan benar, tidak ada None kg / 9000.000 kg, tara 0,1 kg/karung; snapshot 251 tetap terpisah dari tiket kini 261; stok tetap 250.
- Browser Chromium: 20 kombinasi lima lebar × empat tab, tanpa overflow/ID ganda; ukuran tab tetap; keyboard, draft, klik ganda satu POST, delapan navigasi instan dan penolakan tampilan efektif G1/G2 lulus.
- 120 tangkapan penuh desktop/ponsel semua tab dan kondisi memakai respons aplikasi dari database terisolasi. Semua rincian pada panel aktif dibuka. CSS pengambilan sampai bawah tidak masuk aplikasi.
- Image Docker dibangun. Hasil health image dan CI/deploy final dicatat pada laporan output setelah verifikasi.

## Batas

Tidak menjalankan transaksi pada data operasional. Perangkat fisik, Safari/Firefox dan pembaca layar belum diuji. Uji regresi lokal terarah 985 kasus; CI menjalankan keseluruhan 2149 kasus sesudah push. Pemetaan seluruh fungsi lama tetap mengikuti dokumen detail-pengiriman-retur-20261023.md.
