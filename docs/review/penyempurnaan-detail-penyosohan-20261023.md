# Penyempurnaan detail penyosohan — 23 Oktober 2026

## Lingkup

Menindaklanjuti lima temuan penataan dan laporan baris tab mengecil saat membuka Riwayat. Perubahan hanya pada template detail sosoh, partial penyajiannya, stylesheet khusus serta pengujian. Tidak ada perubahan pada layanan/rumus produksi, API tindakan, stok, pencatatan waktu, sesi, CSRF atau komponen bersama.

| Temuan | Perbaikan |
|---|---|
| Jenis dan banyak spek bercampur dalam judul | Ringkasan hasil menampilkan jenis dan total berat terpisah dari rincian “Spesifikasi tercatat”. Semua spek tetap tersedia, tanpa pemotongan. Label jenis tetap dinamis, termasuk jenis warisan. |
| Catat hasil terlalu jauh di bawah | Tombol berada paling atas di tab Hasil, sebelum ringkasan dan riwayat; URL/konteks/borang lama tetap dipakai. Keterangan tombol memperjelas total kumulatif. |
| Identitas terlalu tinggi dan pemilik berulang | Menghapus baris pemilik ganda dan memadatkan jarak serta ukuran judul ponsel. Penanda pemilik/pesanan jasa bersama tetap ditampilkan utuh. |
| Bahan awal tidak selalu eksplisit | Wrapper penyajian khusus menamai “Awal” menjadi “Bahan awal”, sehingga tidak tersembunyi ketika sama dengan total masuk. Nilai yang tidak tersedia tetap “Belum diketahui”. Macro bersama dan sumber angka tidak diubah. |
| Riwayat hasil panjang di ponsel | Tiga baris per catatan: jenis + pertambahan; waktu + pencatat; spek. Desktop tetap tabel. Pagination, jumlah catatan dan seluruh isi tetap dipertahankan. |
| Baris tab mengecil pada Riwayat | Pembungkus detail diberi lebar penuh area kerja, dengan batas maksimum lama. Tab memiliki lebar terbagi rata dan tinggi minimum tetap. Sebelumnya lebar desktop Riwayat 538,44 px sementara tab lain 1.067,84 px; kini semuanya 1.067,84 px. |

Ringkasan hasil hanya memisahkan label tampilan lama pada pemisah pertama ` · `; berat dan daftar spek diberikan langsung oleh layanan lama. Tidak menghitung total/rendemen baru. Rincian silo menggunakan salinan data penyajian sehingga daftar angka asal tidak dimutasi; format, agregasi dan riwayat tetap melalui macro bersama.

## Pemeriksaan

- Seluruh suite non-Postgres: 774 lulus, 7,81 detik.
- Seluruh suite PostgreSQL: 1.271 lulus, 676,56 detik (11 menit 16 detik).
- Suite terarah awal: 22 lulus (detail tab, pemakaian ulang silo, detail empat proses).
- Macro khusus diuji untuk nilai awal sama dengan total, angka belum diketahui, pemakaian ulang, serta data lama tanpa angka awal; input dan macro proses lain tidak berubah.
- Ringkasan hasil diuji dengan Premium, Beras B, Bekatul dan jenis tambahan; spek dengan koma/pemisah/karakter HTML tetap utuh dan di-escape. Berat tetap memakai nilai yang diberikan.
- Tiga peran Admin, Super Admin dan operator tetap diperiksa melalui suite detail; cookie gudang efektif dan endpoint langsung juga diuji.
- Browser langsung pada database uji: perpindahan instan berulang mempertahankan konteks dan lebar tab. Tombol baru membuka borang lama; kumulatif 4.700 lalu 4.800 kg masing-masing menghasilkan tambahan 100 kg dan satu POST walau Simpan diklik ganda. Tidak ada galat JavaScript.
- Ukuran baris tab di semua panel: desktop 1.067,84 × 49 px pada viewport 1440 × 1000; ponsel 358 × 49 px pada viewport 390 × 844. Setiap target tab tingginya 48 px. Tidak ada overflow horizontal pada ukuran tersebut.
- Pemeriksaan tambahan lebar 320, 768 dan 1.920 px: tab tetap konsisten pada keempat panel, tanpa overflow horizontal.
- Tangkapan panjang seluruh tab, dua halaman hasil, seluruh rincian bahan/pemakaian/asal silo dan spek dibuka: setiap footer masuk gambar dan tidak ada isi yang terpotong. CSS perluasan area gulir hanya disuntikkan saat tangkapan, bukan perubahan aplikasi.
- Pemeriksaan diff memastikan tidak ada berkas layanan/API/formulir lama atau paket vendored yang berubah. `git diff --check` lulus.

Database pengujian baru: `uji_sosoh_rapi`, hanya loopback port 55449 di klaster `/tmp/hmu-sosoh-pg`; skema dari migrasi repository. Pemeriksaan browser memakai `uji_sosoh_bersih`, database uji terpisah di klaster yang sama. Tidak menyentuh data operasional.

## Artefak

Di workspace `produksi/output/detail-sosoh/penyempurnaan/`:

- `desktop/ponsel-{ringkasan,bahan,hasil,riwayat}-lengkap.png`.
- `desktop/ponsel-hasil-halaman-2-lengkap.png`.
- `bukti-browser.json`: pengukuran tab dan verifikasi footer/rincian.
- `alur-browser.json`: navigasi instan, delta kumulatif dan jumlah POST.
- Log pengujian dan salinan laporan ini.

Batas verifikasi: Chromium desktop dan emulasi ukuran ponsel; belum diuji pada perangkat ponsel fisik atau Safari/iOS. Tidak mengklaim bahwa ukuran tangkapan panjang adalah tinggi layar asli.
