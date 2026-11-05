# Ringkasan bahan titipan dan kontrol Pesanan Jasa

Daftar pelanggan dan kelima tab detail menggunakan `_jasa_kontrol.html`, `jasa-kontrol.css` dan `jasa-kontrol.js` dari paket tampilan. Panduan memakai kerangka `_panduan.html`. Kartu pelanggan, seluruh tab, tautan, paginasi, rekap, serta gerbang tutup/batal tetap tersedia. Pesanan baru tetap melalui Pos Timbang.

`jasa_bahan.ringkas` membuat proyeksi per jenis dan tahap dari baris stok yang dibaca `jasa_pelanggan`. Tidak ada total gabungan bahan, PK dan hasil. Gabah ditampilkan sebagai menunggu penempatan, tumpukan, pengering, dan silo/proses giling. PK menunggu penempatan/transfer dan bahan di silo sosoh ditampilkan terpisah dari PK bebas serta produk tersedia.

Bobot `None` tetap belum diketahui. Jika hanya sebagian bobot diketahui, angka diberi label subtotal tercatat dan jumlah catatan tanpa bobot disebutkan. Angka perkiraan atau saldo terikat proses ditandai belum final. Identitas sumber mencegah penggandaan saat proyeksi disusun.

Pembaca tetap memakai `dari_batch`, `_row_bobot`, dan `pending_gabah_kering_kg`. Bahan di silo G2 memakai `hitung_stok_silo`, `pemilik_silo_g2`, dan `komposisi_bahan_silo`; jenis master silo tidak dipakai untuk menebak seluruh isinya sebagai PK. Hanya pemilik yang terbukti masuk dalam ID pesanan pelanggan yang ditampilkan. Gudang dilabeli dari ID warehouse sebenarnya; tidak dipetakan lewat nama.

Perhitungan PK bebas, beras dan hasil samping lama tidak ditambah dengan bahan proses. Semua penambahan adalah SELECT/proyeksi tampilan; tidak ada migrasi, pengalihan kepemilikan, atau perubahan transaksi.
