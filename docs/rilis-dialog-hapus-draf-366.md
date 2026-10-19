# Dialog Hapus draf — versi 366

Konfirmasi memakai dialog aplikasi bertema, bukan confirm bawaan browser.
Nama pelanggan dan jumlah item ditampilkan terpisah; nama panjang membungkus.
Batal mendapat fokus awal. Batal, Escape, dan ketukan backdrop menutup dialog
tanpa mengirim permintaan hapus. Sebelum menyetujui, identitas sesi diperiksa
kembali. Pemeriksaan pemilik/revisi pada server tetap berlaku.

Uji simulasi lokal 320/390/1440 px terang dan gelap: 78 uji browser/kontras dan
87 pemeriksaan pendukung lulus. Enam uji dialog diulang setelah penambahan
pemeriksaan pergantian sesi dan lulus. Batal tidak mengirim POST dan draf tetap
utuh. Uji gagal jaringan, ulang hapus, fokus, dan Escape setelah persetujuan
sebelumnya turut lulus. Tidak ada perubahan skema atau data operasional.
