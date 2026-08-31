# Rancangan Sistem — Webapp Timbangan

**PT Hadi Mulya Utama · Pos timbang: pencatatan, kontrol, dan monitoring**
Versi rancangan 2.0 · 25 Agustus 2026

Desain layar: <https://claude.ai/code/artifact/f5303cbe-3c5f-414d-a533-ad5a4f683770> — 28 layar, berkas sumber di `docs/timbangan/design/`.

Rujukan:
- **SOP Internal Kontrol Pembelian Gabah** — gabah basah *(dokumen resmi)*
- **Sistem Tara & Pembelian Beras Pecah Kulit (PK)** *(dokumen resmi)*
- **Gabah kering, barang keluar, jasa timbang** — arahan Direksi 25 Agustus 2026 *(belum tertulis; draf SOP gabah kering tersedia di `DRAF-SOP-Gabah-Kering.md`)*

---

## 1. Lingkup

Modul ini **murni timbangan**. Tidak ada harga, nilai transaksi, atau perhitungan uang apa pun di dalamnya — semuanya milik pembelian dan keuangan (Kledo & modul pabrik).

> **Operator pos timbang tidak boleh mengetahui harga.** Tidak ada satu pun kolom harga di seluruh layar, sehingga secara rancangan mustahil bocor dari sini.

Yang dicatat: siapa, membawa apa, dengan kendaraan apa, berapa beratnya, jam berapa, dan apakah wajar dibandingkan dokumen yang dibawa.

---

## 2. Arsitektur & Stack

Peta tingkat sistem — tiga modul, fondasi bersama, kepemilikan tabel, dan aturan operasional Railway — ada di [`docs/ARSITEKTUR.md`](../ARSITEKTUR.md). Bagian ini hanya bagian yang menyangkut modul timbangan.

### 2.1 Dua service, satu database

Modul ini berjalan sebagai **service Railway sendiri**, terpisah dari agen AI dan bot Telegram, tetapi memakai **repo, image, dan PostgreSQL yang sama**.

```
   HP petugas (Android / iOS)                  Printer 80 mm
   ┌──────────────────────────┐                AirPrint · Mopria
   │  PWA — layar utama       │                       ▲
   │  ┌────────────────────┐  │   WiFi pos            │
   │  │ Service worker     │  │───────────────────────┘
   │  │ IndexedDB          │  │   halaman cetak 72 mm
   │  │  · draf per ketikan│  │
   │  │  · antrean kirim   │  │
   │  │  · master lokal    │  │
   │  └────────────────────┘  │
   └───────────┬──────────────┘
               │ HTTPS
   ════════════▼═══════════════ RAILWAY ════════════════════
   │                                                        │
   │  Service: timbangan          Service: app  (sudah ada) │
   │  ┌──────────────────┐        ┌───────────────────────┐ │
   │  │ FastAPI          │        │ FastAPI + bot Telegram│ │
   │  │ /timbangan/*     │        │ + poller · 1 replica  │ │
   │  │ deploy bebas     │        │ pemilik migrasi       │ │
   │  └────────┬─────────┘        └───────────┬───────────┘ │
   │           └────────────┬─────────────────┘             │
   │              Service: PostgreSQL                       │
   │              timbangan_* · suppliers · users           │
   ═════════════════════════════════════════════════════════
```

**Mengapa dipisah.** Bot Telegram memakai long-polling dan wajib satu replica; setiap deploy memutus polling dan menghentikan poller sesaat. Aplikasi timbangan yang sedang aktif dibangun akan sering di-deploy — bila menempel di proses yang sama, tiap perbaikan kecil ikut mengganggu bot dan notifikasi. Memisahkan service memutus ketergantungan itu, sekaligus mencegah bug di timbangan menjatuhkan agen.

**Cara berbaginya:**

| Hal | Aturan |
|---|---|
| Repo & image | Satu, dengan dua perintah start berbeda |
| Database | Satu `DATABASE_URL`; tabel `timbangan_*`, `suppliers`, `users` dipakai bersama |
| Migrasi Alembic | Satu riwayat, tetapi **hanya service `app` yang menjalankannya saat start** — bila keduanya menjalankan, deploy bersamaan akan berebut |
| Integrasi agen | Agen membaca tabel yang sama lewat bundel tool `timbangan`; tidak ada panggilan HTTP antar-service |

### 2.2 Stack

| Lapisan | Pilihan |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Database | PostgreSQL di Railway + SQLAlchemy 2 async (asyncpg) + Alembic |
| Tampilan | Jinja2 server-rendered, CSS & JS biasa — tanpa framework, tanpa build step |
| Aplikasi di HP | PWA: service worker + IndexedDB, dipasang ke layar utama |
| Autentikasi | scrypt (pustaka standar) + cookie bertanda tangan HMAC-SHA256 |
| Grafik | SVG digambar sendiri, tanpa pustaka chart |
| Cetak | Halaman HTML `@page 72mm` lewat dialog cetak sistem |
| Ekspor | CSV (stdlib), XLSX (openpyxl), PDF (reportlab) |

Tambahan pada `requirements.txt`: `jinja2`, `python-multipart`, `openpyxl`, `reportlab`.

Tidak ada JavaScript framework. Alasannya bukan selera: tanpa build step, lapisan offline jauh lebih sederhana, halaman ringan di HP murah, dan seluruh sistem perusahaan tetap satu bahasa.

### 2.3 Lapisan di dalam modul

```
routes/     HTTP, form, render          ← boleh tahu framework
service/    query, penomoran, audit,    ← boleh tahu database
            aturan kunci, agregasi
logic.py    rumus, ambang, status,      ← tidak tahu apa pun
            skor, deteksi pola             selain angka
```

`logic.py` tidak menyentuh database maupun FastAPI. Itu yang membuat tiga contoh resmi dapat diuji tanpa menyalakan apa pun, dan nanti dipakai ulang agen AI tanpa menyeret separuh aplikasi.

### 2.4 Alur sinkronisasi

```
ketik → draf di IndexedDB (tiap ketikan)
      → SIMPAN: transaksi sah + masuk antrean kirim
      → sinkron latar: kirim satu per satu saat sinyal ada
      → server menerima berdasarkan KODE transaksi
```

Karena kode transaksi dibuat perangkat, pengiriman ulang tidak pernah menghasilkan transaksi ganda: kode yang sudah ada diabaikan. Itulah yang membuat antrean kirim aman dicoba berkali-kali.

### 2.5 Batas yang dijaga arsitektur

- **Tidak ada kolom harga** di seluruh basis data modul ini — kerahasiaan harga bukan aturan yang bisa dilanggar, melainkan sesuatu yang tidak tersedia. Sama untuk potongan mutu.
- **Audit hanya bertambah**, tidak pernah ditimpa.
- **Hak akses ditegakkan di rute**, bukan dengan menyembunyikan menu.
- **Master supplier & pengguna dipakai bersama** modul pabrik; `suppliers.kledo_contact_id` disiapkan untuk sinkronisasi Kledo.

---

## 3. Komoditas dan arah

| Komoditas | Kode | Masuk | Keluar |
|---|:--:|:--:|:--:|
| Gabah basah | GB | ✅ | — |
| Gabah kering | GK | ✅ | — |
| Beras PK | PK | ✅ | — |
| Beras | BS | ✅ | ✅ |
| Broken | BR | ✅ | ✅ |
| Menir | MN | — | ✅ |
| Bekatul | BK | — | ✅ |
| Reject | RJ | — | ✅ |
| Timbang bebas (jasa) | — | ✅ | ✅ |

Reject, bekatul, dan menir tidak pernah dibeli. Beras dan broken bergerak dua arah.

---

## 4. Alur di pos timbang

### 4.1 Dua kali timbang

```
BARANG MASUK                          PENGIRIMAN
1. truk bermuatan                     1. truk kosong
   ↓ bongkar                             ↓ muat
2. truk kosong                        2. truk bermuatan

netto timbangan = bermuatan − kosong     (rumus sama, urutan terbalik)
```

Di antara keduanya, tiket **tersimpan terbuka**. Beberapa truk boleh menunggu bersamaan. Bila bongkar/muat selesai saat itu juga, kedua angka boleh diisi sekaligus.

**Tenggat tiket terbuka:** 4 jam ditandai kuning di layar operator, 8 jam masuk daftar tindakan supervisor, lewat pergantian hari dikirim ke penanggung jawab.

### 4.2 Jasa timbang boleh sekali

Cara timbang dipilih **di awal** — Sekali atau Dua kali — supaya sistem bisa membedakan "memang cukup sekali" dari "lupa diisi". Mode sekali langsung berstatus selesai dan tidak pernah masuk daftar menunggu.

Disertai keterangan **yang ditimbang**: truk bermuatan, truk kosong, atau lainnya. Tiketnya menulis **BERAT TERTIMBANG**, bukan netto muatan — dengan sekali timbang, berat barang memang tidak diketahui.

### 4.3 Truk yang tidak jadi bongkar

Ditolak QC, harga tidak sepakat, atau salah kirim → tombol **Tidak jadi bongkar**. Alasan wajib dipilih, catatan dan nama pemutus dicatat.

**Truk tetap ditimbang saat keluar** meski pulang bermuatan. Selisih masuk − keluar adalah kontrolnya: mendekati nol berarti muatan utuh; selisih besar berarti ada yang diturunkan meski dinyatakan ditolak, dan wajib dijelaskan sebelum tiket ditutup.

Barang diterima **0 kg** — tidak masuk tonase, tidak dihitung sebagai selisih, tetapi tetap tercatat sebagai kunjungan supplier.

### 4.4 Tanggal transaksi

**Mengikuti timbang kedua**, saat angkanya lengkap. Rekap harian, dashboard, monitoring, dan ekspor semuanya memakai tanggal itu.

Nomor transaksi tetap bertanggal saat tiket **dibuka** dan tidak pernah berubah — jadi wajar bila rekap 24 Agustus memuat nomor bertanggal 23; keterangan *"dibuka 23 Agu 16.40"* ditampilkan di bawah kodenya.

> **Konsekuensi untuk gudang:** barang yang masuk sore tanggal 23 tercatat sebagai transaksi tanggal 24. Saat mencocokkan stok harian, selisih semalam ini sumber bingung yang paling sering.
>
> **Imbalannya:** tiket terbuka tidak pernah masuk rekap mana pun, dan angka rekap tidak berubah lagi setelah harinya lewat.

---

## 5. Aturan per komoditas

| Komoditas | Tara/karung | Pembanding | Batas wajar |
|---|---|---|---|
| Gabah basah | 0,25 kg tetap | Nota supplier | ±2 kg per ton nota · investigasi >5 kg/ton |
| Gabah kering | 0,25 kg tetap | Nota supplier | Kurang maks 0,5 kg per ton · kelebihan bebas |
| Beras PK | Sampling per pihak × komoditas, bawaan 0,1 kg | Nota supplier | Kurang maks 0,05 kg per karung |
| Broken (masuk) | 0,07 kg tetap | Nota supplier | Kurang maks 0,05 kg per karung |
| Beras (masuk) | *belum ditetapkan* — sementara mengikuti PK | Nota supplier | Kurang maks 0,05 kg per karung |
| Barang keluar — beras, broken, menir, bekatul, reject | 0,05 kg tetap *(broken 0,07)* | Surat jalan | 0 s/d +0,07 kg per karung · **kurang tidak boleh** |
| Timbang bebas | Manual, bawaan 0 | — | — |

Aturan ini hidup di **master jenis timbang**, bukan di kode. Menambah komoditas atau mengubah ambang = mengisi satu baris.

### 5.1 Rumus

**Masuk — dibandingkan nota**

```
Netto timbangan = bermuatan − kosong
Total tara      = jumlah karung × tara komoditas
Netto kontrol   = netto timbangan − total tara
Selisih         = netto kontrol − berat nota
```

**Keluar — dibandingkan surat jalan**

```
Berat barang = netto timbangan − (jumlah karung × tara)
Selisih      = berat barang − berat surat jalan

selisih < 0                    → KURANG, boleh ditutup paksa dengan alasan
0 s/d +0,07 × jumlah karung    → NORMAL
di atas itu                    → KELEBIHAN, perlu diperiksa
```

**Pengiriman beberapa komoditas** — jembatan hanya memberi satu netto, jadi kontrolnya di tingkat total:

```
Total berat barang = netto timbangan − Σ(karung ᵢ × tara ᵢ)
Selisih            = total berat barang − Σ berat surat jalan
Toleransi          = Σ karung ᵢ × 0,07
```

Sistem **tidak memecah berat per komoditas** — angka itu tidak terukur, dan mengarangnya membuat orang percaya pada angka palsu.

### 5.2 Verifikasi terhadap contoh resmi

| | SOP Gabah | Spesifikasi Direksi | Sistem Tara PK |
|---|---|---|---|
| Netto timbangan | 20.220 kg | 10.030 kg | 14.000 kg |
| Karung × tara | 800 × 0,25 = 200 | 120 × 0,25 = 30 | 200 × 0,085 = 17 |
| Hasil | **20.020 kg** | **10.000 kg** | **13.983 kg** |
| Pembanding | Nota 20.000 | Nota 10.048 | Nota 13.990 |
| Selisih | **+20 kg** | **−48 kg** | **−7 kg** |
| Status | NORMAL | PERLU PEMERIKSAAN | NORMAL |

Ketiganya jadi kasus uji otomatis.

> **Kapasitas jembatan timbang 20 ton.** Angka di atas itu ditolak sebagai mustahil. Contoh PK pada rancangan v1.x memakai bruto 25,4 ton — mustahil di jembatan ini, sudah diperbaiki.

---

## 6. Tara standar supplier (komoditas bersampling)

Satu tara aktif per **pihak × komoditas**. Jenis karung tercatat sebagai keterangan; bila berganti, wajib sampling ulang.

```
Tara standar   = total berat sampel ÷ jumlah sampel   (minimal 30 karung)
Berlaku sampai = tanggal sampling + 90 hari
```

Pihak yang belum disampling memakai **tara bawaan 0,1 kg/karung** sampai samplingnya dilakukan — transaksi tidak diblokir, pekerjaan tetap jalan. Tara baru berlaku setelah disetujui **Wahid**. Riwayat sampling lama tidak pernah dihapus, sehingga keberatan pihak lawan bisa ditelusuri.

---

## 7. Ketahanan & integritas

### 7.1 Tahan sinyal putus

Pos timbang bersinyal lemah; angka yang hilang tidak bisa ditimbang ulang karena truk sudah pergi.

| Lapis | Cara kerja |
|---|---|
| Draf | Tiap ketikan disimpan ke perangkat — aplikasi ditutup atau HP mati, angka tetap ada |
| Simpan lokal | Transaksi sah begitu disimpan, tanpa menunggu jaringan |
| Antrean kirim | Terkirim sendiri saat sinyal kembali; bertahan meski aplikasi ditutup |

**Nomor transaksi tidak minta ke server:** `TRX-<tanggal>-<kode pos>-<urutan perangkat>`. Final sejak awal, sehingga bukti timbang boleh langsung dicetak; dua perangkat offline tidak bertabrakan. Master data (komoditas, tara, pihak, kendaraan) disimpan di perangkat agar form tetap menghitung tanpa jaringan.

Yang gagal karena data kurang — misalnya kendaraan belum terdaftar — ditandai merah dan bisa diperbaiki **tanpa mengetik ulang angka timbang**.

### 7.2 Penjaga salah ketik

| Tingkat | Cara |
|---|---|
| Halus | Titik ribuan otomatis saat mengetik; garis riwayat *"kendaraan ini biasanya 12,0–14,2 ton"* |
| Sedang | Peringatan di bawah kolom: di luar kebiasaan kendaraan, atau bukan kelipatan 10 kg. Boleh dilanjutkan |
| Keras | Ditolak: melebihi 20 ton, kosong lebih berat dari bermuatan, netto negatif |

Peringatan tidak muncul sebagai jendela yang menutup layar — itu akan dipencet refleks dalam seminggu. Yang menahan hanya layar konfirmasi: tombol simpan mati sampai dicentang *"saya sudah cek display"*, dan centang itu ikut tersimpan.

Rentang kebiasaan lahir dari riwayat kendaraan itu sendiri; kendaraan baru tidak dibatasi sampai punya cukup riwayat.

### 7.3 Jam

**Jam sistem tersimpan permanen dan tidak bisa diubah.** Koreksi hanya *menambah* "jam menurut operator" beserta alasannya; keduanya tampil berdampingan.

### 7.4 Sesi & perangkat

Kata sandi diminta **sekali**, saat perangkat pertama dipakai. Sesudah itu aplikasi terbuka langsung di beranda setiap kali dibuka — termasuk tanpa sinyal, karena sesi tersimpan di perangkat dan tidak diminta ke server. Sesi hanya berakhir bila pengguna menekan **Keluar**, yang diletakkan di dalam menu.

**Satu perangkat, satu orang.** Tiap petugas memakai perangkatnya sendiri, sehingga tidak ada layar ganti pengguna maupun PIN, dan nama yang menempel pada transaksi selalu benar tanpa tindakan tambahan. Bila perangkat sesekali dipinjam, jalannya satu: pemilik menekan Keluar, peminjam masuk dengan kata sandinya sendiri.

Tiap perangkat mendapat kodenya sendiri (`P1`, `P2`, …) yang masuk ke nomor transaksi — syarat agar penomoran offline tidak pernah bertabrakan antar-perangkat.

### 7.5 Petugas

Terisi otomatis dari akun yang login. Karena timbang dilakukan dua kali dan bisa oleh orang berbeda, **keduanya tercatat** — T1 dan T2. Yang tertera sebagai *petugas timbang* pada bukti cetak adalah pelaku **timbang kedua**, karena dialah yang menutup transaksi.

### 7.6 Penutupan pemeriksaan

Status kontrol — NORMAL, PERLU PEMERIKSAAN, INVESTIGASI — **tidak pernah berubah**. Itu fakta tentang angkanya; mengubahnya berarti memalsukan riwayat.

Yang punya penutup adalah tindak lanjutnya: **BELUM DIPERIKSA → SEDANG DIPERIKSA → TUNTAS**. Menutup wajib menyertakan kategori hasil dan catatan resolusi.

| Kategori hasil |
|---|
| Susut perjalanan · Salah catat nota · Salah hitung karung · Salah input · Timbang ulang di asal · Penyebab tidak ditemukan |

Kategori inilah yang membuat pemeriksaan menjadi data. Catatan bebas hanya bisa dibaca satu per satu; kategori memungkinkan melihat penyebab yang paling sering — per supplier maupun per kendaraan. *"Penyebab tidak ditemukan"* yang berulang pada satu supplier adalah temuan tersendiri.

Dashboard dan daftar transaksi hanya menghitung yang **belum tuntas** sebagai perlu tindakan.

### 7.7 Koreksi dan pembatalan

| Peran | Boleh mengubah |
|---|---|
| Staff | Transaksi miliknya, selama belum 24 jam |
| Supervisor & Admin | Semua, termasuk yang terkunci |

Alasan wajib. Nilai lama tidak pernah ditimpa diam-diam: audit menyimpan sebelum, sesudah, alasan, pelaku, jam. Bila koreksi mengubah status, lembar pemeriksaan yang sudah ditutup dibuka kembali. Transaksi tidak pernah dihapus — hanya **VOID** beralasan, tetap tersimpan dan tampil tercoret.

### 7.8 Cetak ulang

Cetakan kedua dan seterusnya berkepala **CETAKAN ULANG** beserta nomor urut, pelaku, dan alasannya, sehingga tidak beredar sebagai dokumen kedua yang setara.

### 7.9 Foto bukti

Opsional pada transaksi normal; **wajib** saat selisih melewati ambang — di situlah bukti paling dibutuhkan dan truknya masih ada. Foto disimpan di database, bukan di disk: filesystem Railway sementara, bukti tidak boleh hilang.

### 7.10 Identitas pihak & kendaraan

Dipilih dari master dengan pencarian, bukan diketik bebas. Ketik `b12`, `1234`, atau `xyz` → menemukan kendaraan yang sama; penulisan dirapikan jadi `B 1234 XYZ`. Tanpa ini, `B1234XYZ` dan `B 1234 XYZ` jadi dua kendaraan dan analisis pola rusak diam-diam.

---

## 8. Kepatuhan SOP

### 8.1 SOP Gabah — sesuai

Dasar transaksi tetap nota; timbangan sebagai kontrol internal; tara 0,25 kg/karung; rumus identik; batas kewajaran dengan tindakan pemeriksaan; bahasa netral; kerahasiaan hasil kontrol. Langkah butir 6 dijadikan **lembar pemeriksaan wajib** yang harus ditutup, dengan **Miftah** sebagai penanggung jawab.

### 8.2 Sistem Tara PK — sesuai, dua catatan

Dasar pembayaran PK bersih; tera dua arah; tara dari sampling ≥30 karung per pihak; ganti karung → sampling ulang; verifikasi 90 hari; keberatan → sampling ulang; enam angka wajib pada nota timbang; perubahan disetujui pihak berwenang (**Wahid**).

**Larangan potongan tetap ditegakkan lewat rancangan:** tidak ada satu pun kolom potongan di basis data, jadi secara teknis tidak bisa dilakukan.

Dua hal berbeda dari dokumen — lihat `DRAF-REVISI-Sistem-Tara-PK.md`:
1. **Refaksi kualitas** diatur di butir 5 & 8 tetapi tidak dipakai dalam praktik
2. **Tara bawaan 0,1 kg** untuk pihak yang belum disampling — tidak diatur dokumen

### 8.3 Di luar SOP — perlu pasal tambahan

Ambang proporsional per ton, aturan barang keluar terhadap surat jalan, tutup paksa, jasa timbang, skor supplier, deteksi pola, kunci 24 jam, VOID, tenggat tiket terbuka.

---

## 9. Model Data

Tiga belas tabel `timbangan_*`, ditambah kolom `suppliers.kledo_contact_id` sebagai jembatan sinkronisasi Kledo. Master `suppliers` dan `users` yang sudah ada dipakai ulang — tidak ada master tandingan.

| Tabel | Isi |
|---|---|
| `timbangan_jenis` | Aturan per komoditas: arah, mode, sumber tara, nilai tara, jenis & nilai ambang, arah ambang, sifat rahasia, cetak bukti, masa berlaku tara |
| `timbangan_transaksi` | Satu kedatangan truk: arah, jenis, cara timbang, dua angka timbang + jam sistem + jam operator + petugas masing-masing, hasil hitung, status, jejak perangkat & pengiriman |
| `timbangan_muatan` | Baris muatan: jenis, nomor surat jalan/nota, jumlah karung, tara dipakai, berat acuan. Satu baris untuk masuk, beberapa untuk pengiriman |
| `timbangan_tara_standar` | Sampling per pihak × komoditas: jumlah sampel, total berat, tara hasil, jenis karung, masa berlaku, alasan, penyetuju |
| `timbangan_pemeriksaan` | Lembar SOP butir 6: enam langkah, catatan per langkah, penerima laporan, kategori hasil, catatan resolusi, status, penutup & waktunya |
| `timbangan_cetak` | Riwayat cetak: urutan, asli/ulang, alasan, pelaku, waktu |
| `timbangan_foto` | Bukti (BLOB), jenis, pengunggah |
| `timbangan_akun` | Kredensial & peran login browser, tertaut ke `users` |
| `timbangan_kendaraan` | Master armada, nomor polisi dinormalkan |
| `timbangan_supplier_profil` | Atribut monitoring supplier, terpisah dari identitas agar aman ditimpa Kledo |
| `timbangan_skor_supplier` | Cache skor & kategori |
| `timbangan_audit` | Siapa, kapan, aksi apa, nilai sebelum-sesudah |
| `timbangan_config` | Setelan operasional yang boleh diubah Admin dari layar; baris kosong berarti ikut environment |

### 9.1 Keputusan pemodelan

**a. Aturan hidup di data.** Menambah komoditas = satu baris master.
**b. Salinan aturan di tiap transaksi.** Revisi SOP tidak mengubah masa lalu.
**c. Muatan selalu berupa baris.** Masuk satu baris, keluar beberapa — satu bentuk data, bukan dua.
**d. Tidak ada kolom harga maupun potongan.** Larangan ditegakkan oleh ketiadaan kolom.
**e. Tara standar tidak pernah ditimpa.** Sampling baru = baris baru; yang lama DIGANTI atau KEDALUWARSA.
**f. Angka timbangan mentah.** Sistem tidak membulatkan; pembulatan tera sudah dikerjakan alat.
**g. Nomor transaksi dibentuk di perangkat.** Syarat agar bisa bekerja tanpa jaringan.

### 9.2 Jembatan integrasi

`purchase_batch_id` dan `pk_purchase_batch_id` disiapkan sejak awal, dibiarkan kosong. Saat integrasi diaktifkan: gabah menaut ke `purchase_batches` dengan **berat nota**; PK menaut ke `pk_purchase_batches` dengan **berat PK bersih**. Webapp tidak membuat pencatatan pembelian tandingan.

---

## 10. Peran & Akses

Direvisi **30 Agustus 2026** (keputusan #6, #7, dan #9 di §12). **Tiga peran.**

| Kemampuan | Petugas | Admin | Super Admin |
|---|:--:|:--:|:--:|
| Menimbang, membuka & mencetak **hasil sendiri** | ✅ | ✅ | ✅ |
| Membuka catatan **orang lain** | — | ✅ | ✅ |
| Daftar catatan (menu Catatan) | — | ✅ | ✅ |
| Ringkasan, monitoring, ekspor | — | ✅ | ✅ |
| Koreksi < 24 jam (miliknya) | ✅ | ✅ | ✅ |
| Koreksi setelah terkunci, VOID | — | ✅ | ✅ |
| Tutup paksa pengiriman kurang | ✅ | ✅ | ✅ |
| Tutup lembar pemeriksaan | — | ✅ | ✅ |
| Catat sampling tara | — | ✅ | ✅ |
| Setujui tara standar | — | ✅ | ✅ |
| Ubah **akun sendiri** — nama, nama pengguna, sandi | ✅ | ✅ | ✅ |
| Ubah peran & kode perangkat siapa pun | — | — | ✅ |
| Tambah, nonaktifkan, hapus pengguna | — | —¹ | ✅ |
| Master jenis, pihak, kendaraan | lihat | ✅ | ✅ |
| Ubah setelan operasional (5 parameter) | — | — | ✅ |
| **Baca jejak audit** | — | — | ✅ |
| **Hapus catatan timbang permanen** | — | — | ✅ |
| **Angkat / ubah / hapus akun Super Admin** | — | —¹ | ✅ |

¹ Kecuali selama **belum ada Super Admin aktif** — supaya yang pertama bisa
dibuat, dan supaya masih ada jalan pulih bila satu-satunya hilang. Begitu ada
satu yang aktif, pintunya tertutup: Admin tidak bisa mengangkat Super Admin
baru, tidak bisa mengubah, menonaktifkan, maupun menghapus akun Super Admin.
Tanpa pagar itu pemisahan perannya tidak berarti apa-apa — Admin mana pun
tinggal mengangkat dirinya sendiri, atau menonaktifkan Super Admin yang ada
lalu mengangkat dirinya. Dijaga di keempat pintunya: membuat akun, mengubah
akun, mengubah status, dan menghapus akun.

Sejak **31 Agustus 2026** seluruh halaman Pengguna ikut tertutup bagi Admin
(keputusan #13), sehingga pintu daruratnya menjadi satu-satunya jalan
membuat Super Admin pertama. Setelah berhasil, pelakunya diantar ke
Pengaturan beserta penjelasan — bukan ke daftar pengguna yang baru saja
tertutup di belakangnya, yang hanya akan terbaca seolah perubahannya gagal.

**Jejak audit hanya untuk Super Admin.** Bukan karena isinya lebih rahasia,
melainkan karena inilah satu-satunya tempat yang masih menyebut siapa pelaku
pada catatan yang namanya sudah dikosongkan, dan satu-satunya salinan penuh
catatan yang sudah dihapus permanen. Ia mengawasi wewenang menghapus — maka
yang membacanya jangan sama dengan yang memakainya sehari-hari. Halamannya
hanya menerima GET; tidak ada rute yang bisa mengubah atau menghapus barisnya.

**Menghapus akun tidak pernah menghapus catatan timbang.** Yang dilepas hanya
penunjuk namanya: baris yang tadinya menyebut orang itu berubah menjadi tidak
menyebut siapa-siapa; angka, tanggal, selisih, dan statusnya utuh. Admin hanya
boleh menghapus akun yang belum meninggalkan jejak kerja; **Super Admin** boleh
menghapus akun yang sudah bekerja, dan nama pada catatan-catatan itu
dikosongkan — tidak bisa dikembalikan. Setelah itu hanya jejak audit yang masih
bisa menjawab siapa pelakunya, karena `akun_nama` sudah tersimpan sebagai
salinan sejak baris itu ditulis.

**Membatalkan ≠ menghapus.** Membatalkan (VOID) meninggalkan barisnya di
catatan bertanda "Batal" beserta alasannya — truk yang batal bongkar memang
pernah datang, dan menyembunyikan barisnya membuat catatan terlihat rapi
dengan cara yang keliru. Ringkasan, ekspor, dan beranda tetap tidak
menghitungnya. Menghapus meniadakan barisnya sama sekali; itulah sebabnya
wewenangnya dipisahkan ke peran tersendiri, dikunci di balik nomor transaksi
yang harus diketik ulang, menuntut alasan, dan tetap menuliskan salinan penuh
angkanya ke jejak audit. Sebuah catatan boleh hilang dari daftar, tetapi
tidak boleh hilang dari sejarah.

**Menutup daftar saja tidak cukup.** Nomor transaksi di URL berurutan, jadi
rincian ikut dijaga: yang bukan Admin hanya boleh membuka transaksi yang ia
timbang sendiri. Beranda dipersempit dengan aturan yang sama, supaya tidak
memajang tautan yang berujung "akses ditolak".

**Menghapus akun bukan kebalikan dari membuatnya.** Yang bisa dihapus hanya
akun yang belum meninggalkan jejak kerja apa pun — salah ketik saat membuat,
akun percobaan, orang yang batal masuk. Begitu seseorang pernah menimbang,
namanya melekat pada catatan timbang, lembar pemeriksaan, dan riwayat cetak;
menghapusnya berarti dokumen itu ikut hilang atau berubah menunjuk tidak ada
siapa-siapa. Untuk yang sudah bekerja: nonaktifkan. Penjagaannya dibaca dari
metadata, bukan daftar tabel yang ditulis tangan, sehingga tabel baru ikut
terjaga sendiri. Jejak auditnya tidak ikut terhapus — penunjuk akunnya
dilepas, `akun_nama` sudah tersimpan sebagai salinan sejak baris itu ditulis.

**Kode perangkat melekat pada akun, tidak lagi diketik saat masuk.** Dulu
layar masuk memintanya, dan siapa pun yang mengetik kode perangkat orang lain
diam-diam memindahkan deret nomor transaksi ke dirinya — dua perangkat tanpa
jaringan lalu bisa membuat nomor yang sama, persis yang hendak dicegah kode
itu. Sekarang hanya Admin yang menetapkannya.

Ditegakkan di kode pada setiap rute. Sandi scrypt bersalt; cookie HttpOnly + SameSite=Lax + Secure, HMAC-SHA256, berlaku sampai Keluar; login gagal tercatat; ekspor tercatat pelaku dan rentangnya.

---

## 11. Antarmuka

Mobile-first untuk staff, desktop untuk manajemen. Palet dan tipografi mengikuti design system situs perusahaan (`hadimulya-website/static/css/style.css`): warm white `#fbf9f4`, ink `#1a1712`, terracotta `#c25834`, ocean `#2f6e7a`, amber `#8a5a12`; Manrope, Space Grotesk, Space Mono untuk angka.

Status selalu disertai teks, tidak pernah warna saja: **NORMAL** ocean · **PERLU PEMERIKSAAN** amber · **INVESTIGASI** terracotta · **VOID** abu-abu.

Beranda: tiket menunggu di paling atas, sakelar arah, kisi komoditas berkode dua huruf — dua ketukan dari buka aplikasi sampai mengetik angka.

**Satu dokumen cetak:** Bukti Timbang thermal 80 mm. Isinya menyesuaikan komoditas; gabah tidak pernah dicetak untuk supplier karena hasil kontrolnya internal.

### 11.1 Perangkat: Android dan iOS

Aplikasi ini **webapp yang dipasang ke layar utama** (PWA) — satu kode, berjalan di Android maupun iOS lewat browser, tanpa app store dan tanpa persetujuan Apple/Google. Pembaruan langsung sampai ke semua orang begitu di-deploy.

| Kebutuhan | Android | iOS |
|---|---|---|
| Pasang ke layar utama | Chrome menawarkan sendiri | Safari → Bagikan → *Add to Home Screen* (manual, perlu diajarkan sekali) |
| Buka layar penuh tanpa bilah browser | ✅ | ✅ |
| Bekerja tanpa sinyal | ✅ | ✅ sejak iOS 11.3 |
| Simpan draf & antrean kirim | ✅ | ✅ — dipakai harian, jadi tidak kena penghapusan otomatis Safari |
| Sesi tetap masuk | ✅ | ✅ |
| Foto dari kamera | ✅ | ✅ |
| **Cetak ke printer thermal** | ✅ langsung lewat Bluetooth | ❌ **tidak bisa** — iOS tidak mengizinkan browser mengakses Bluetooth |

**Cetak adalah satu-satunya perbedaan yang nyata.** Keputusan Direksi: **printer ber-AirPrint dan Mopria**, dicetak lewat dialog cetak bawaan sistem. Tidak ada relai, tidak ada perangkat tambahan yang harus dijaga tetap menyala.

Konsekuensinya pada rancangan:

| Hal | Akibat |
|---|---|
| Bukti timbang bukan perintah printer, melainkan **halaman cetak** | Ditata dengan CSS `@page { size: 72mm auto; margin: 0 }` — lebar cetak efektif kertas 80 mm |
| Kertas thermal hanya hitam-putih | Tidak ada latar berwarna maupun abu-abu pada dokumen cetak; garis dan bingkai hitam penuh |
| Huruf tidak boleh bergantung internet | Struk memakai monospace bawaan sistem, bukan font dari Google Fonts — agar cetakan sama persis saat pos sedang tanpa internet |
| Menekan Cetak membuka dialog sistem | Satu ketukan lebih banyak daripada cetak langsung. Wajar, dan sekaligus memberi kesempatan memilih printer bila ada lebih dari satu |
| Printer dan HP harus satu jaringan WiFi | Cetak tetap jalan meski **internet mati**, selama WiFi lokal di pos hidup — AirPrint dan Mopria bekerja di jaringan lokal |
| HP yang sedang memakai data seluler | Tidak menemukan printer. Perangkat pos harus tersambung WiFi pos, bukan data seluler |

### 11.2 Printer: spesifikasi pembelian

**Peringatan utama: varian antarmuka menentukan segalanya.** Satu nomor model dijual dalam beberapa varian — USB saja, Bluetooth saja, atau jaringan. AirPrint dan Mopria **hanya ada pada varian jaringan** (Ethernet/WiFi). Model benar tapi varian salah membuat seluruh rencana cetak gagal di iPhone.

**Kandidat:**

| Model | Catatan |
|---|---|
| **Epson TM-m30III** *(utama)* | 80 mm, ringkas, auto-cutter, tersedia varian Ethernet + WiFi. Epson paling mudah dicari di Indonesia beserta sparepart dan servisnya |
| **Epson TM-T88VII** | Kelas lebih berat dan cepat; berlebihan untuk satu pos kecuali volumenya tinggi |
| **Star Micronics mC-Print3** | Alternatif bila Epson sulit didapat; dukungan AirPrint berbeda antar-varian, perlu diverifikasi lebih teliti |

**Hindari:** printer thermal portabel murah yang hanya menyebut Bluetooth. Jenis inilah yang paling banyak beredar di marketplace, dan tidak satu pun bekerja dengan iPhone lewat jalur ini.

**Cara memastikan sebelum membayar — lakukan di toko:**

Minta penjual mencetak dari iPhone di tempat. Buka Safari → halaman apa saja → Bagikan → Cetak, dan lihat apakah printernya muncul tanpa memasang aplikasi apa pun. Muncul dan tercetak berarti cocok. Bila penjual menawarkan *"pakai aplikasi kami dulu"*, berarti tidak cocok. Tes lima menit ini menggantikan seluruh perdebatan spesifikasi — daftar dukungan AirPrint berbeda antar-batch dan antar-negara, jadi lembar spesifikasi saja tidak cukup.

**Daftar periksa pembelian:**

- [ ] Kertas **80 mm** dengan auto-cutter
- [ ] Varian **Ethernet atau WiFi** — bukan USB atau Bluetooth saja
- [ ] Spesifikasi mencantumkan **AirPrint** *dan* **Mopria**
- [ ] **Lolos tes cetak dari iPhone di toko**
- [ ] Dinamai `POS-TIMBANG` saat dipasang, agar tidak tertukar dengan printer kantor
- [ ] Dua rol kertas cadangan disimpan di pos

**Keterbatasan yang perlu diketahui staff:** bila kertas habis, pekerjaan cetak duduk di antrean printer dan operator bisa mengira tiket sudah keluar. Aplikasi tidak dapat mengetahuinya — riwayat cetak mencatat *permintaan* cetak, bukan bukti kertas benar-benar keluar. Untuk itulah tombol **Cetak ulang** beserta riwayat bernomornya ada.


Seluruh 28 layar ada di kanvas desain — termasuk kondisi kosong, kondisi tanpa sinyal, dan kondisi salah ketik, bukan hanya kondisi ideal.

---

## 12. Keputusan Direksi

Seluruh perkara yang dulu menggantung sudah diputus pada **30 Agustus 2026**.

| # | Perkara | Keputusan | Catatan |
|---|---|---|---|
| 1 | **Ambang gabah kering** | Tetap **0,5 kg per ton** | Dipertimbangkan terhadap alternatif 5 kg tetap, lalu ditegaskan tetap proporsional. Konsekuensinya diukur: simulasi 200.000 transaksi jujur memberi **~13%** tetap ditandai perlu diperiksa. Penyebabnya alat, bukan aturan — pembacaan dibulatkan ke kelipatan 10 kg pada dua kali penimbangan. Batas 5 kg tetap menghasilkan angka yang praktis sama (~12%). Yang menurunkannya berarti hanya menaikkan batas: 1,0 kg/ton → ~1% |
| 2 | **Label status** | Tetap **"PERLU PEMERIKSAAN"** | Sistem mencatat temuan; manusia yang menyimpulkan. Label tersimpan permanen dan terbawa ke ekspor, jadi tidak boleh menuduh |
| 3 | **Baris selisih pada bukti pengiriman** | **Tidak dicetak** | Angka kontrol internal tidak ikut dibawa sopir. Bukti tetap dicetak untuk semua komoditas dan ditandatangani sopir sebagai saksi |
| 4 | **Tara beras masuk** | **Meniru beras PK** | Hasil sampling, bawaan 0,1 kg per karung, berlaku 90 hari. Dikunci uji `test_tara_beras_masuk_meniru_beras_pk`. **Hanya taranya yang diputuskan** — ambang 0,05 kg/karung dan nota yang diberikan ke pengirim masih usulan penyusun dan boleh dibedakan dari PK kapan pun |
| 6 | **Ringkasan & Catatan** | **Admin saja** | Berlaku untuk Pengawas juga. Selain Admin, Pengaturan hanya menyediakan akun sendiri: nama lengkap, nama pengguna, sandi. Peran dan kode perangkat tetap wewenang Admin, karena keduanya menentukan apa yang boleh dikerjakan dan nomor transaksi apa yang keluar dari perangkat. Akibat lanjutannya pada peran Pengawas segera diputus di #7 |
| 7 | **Peran Pengawas** | **Dihapus** — tinggal Admin dan Petugas | Sejak rekapitulasi menjadi wewenang Admin (#6), Pengawas tidak lagi punya satu pun kemampuan yang tidak dimiliki petugas. Peran yang tidak berarti apa-apa lebih buruk daripada tidak ada: ia terlihat seperti pengaman padahal bukan. Pembatalan (VOID) dan penutupan lembar pemeriksaan ikut menjadi wewenang Admin. Migrasi `0026` menurunkan akun berperan PENGAWAS menjadi PETUGAS — diturunkan, bukan dinaikkan, agar tidak ada yang diam-diam menerima wewenang penuh tanpa pernah diputuskan |
| 8 | **Barang masuk: jumlah karung sebelum diselesaikan** | **Wajib** — dengan tombol **Simpan sementara** sebagai jalannya | Seluruh komoditas masuk bertara per karung, jadi tanpa angka itu berat barang dan selisihnya keliru — dan statusnya tersimpan permanen serta terbawa ke ekspor. Karena jumlah karung sering baru pasti setelah bongkar rampung, timbang kedua boleh disimpan lebih dulu: angkanya aman dari HP mati atau shift berganti, tiketnya tetap terbuka, dan yang ditunda adalah perhitungannya — selisih tidak dihitung, status kontrol tidak diberikan, lembar pemeriksaan tidak dibuka. Menghitung selisih tanpa jumlah karung akan memberi angka yang salah sekaligus meyakinkan: tara total nol membuat barang tampak berlebih. Alur pengiriman tidak ikut berubah |
| 9 | **Peran Super Admin** | **Ada** — sama seperti Admin, tambah wewenang menghapus data | Dipisahkan justru supaya pekerjaan sehari-hari tidak dilakukan sambil memegang tombol yang tidak bisa dibatalkan. Sekaligus ditegaskan: transaksi yang dibatalkan **tetap tertera** di catatan timbang bertanda "Batal", dan tidak dihitung dalam ringkasan maupun ekspor. Rinciannya di §10 |
| 10 | **Transfer internal** | **Arah keempat**, satu jenis komoditas saja | Perpindahan barang di dalam perusahaan sendiri. Alurnya sama seperti barang masuk: armada datang bermuatan, ditimbang ulang setelah selesai dibongkar. Tidak dirinci per komoditas — cukup satu jenis "Transfer Internal"; isinya ditulis di catatan bila perlu. Asal dan tujuan ditulis bebas pada satu kolom (mis. "Gudang 1 → Gudang 2"), tanpa master lokasi tersendiri. **Tanpa dokumen pembanding dan tanpa status kontrol**: tidak ada pihak lawan yang perlu dikontrol, jadi yang dicatat cukup berapa yang berpindah. Kolom dokumen sengaja tidak ditampilkan — menyediakannya hanya mengundang angka yang tidak akan pernah dipakai |
| 11 | **Menghapus akun yang sudah bekerja** | **Boleh, oleh Super Admin** — catatan tidak ikut terhapus, namanya saja dikosongkan | Rinciannya di §10 |
| 12 | **Nomor polisi** | **Wajib** untuk barang masuk dan barang keluar | Keduanya melibatkan pihak luar, jadi catatannya harus bisa menunjuk kendaraan tertentu bila kelak ada sengketa. Jasa timbang dan transfer internal dibiarkan boleh kosong — tidak selalu memakai kendaraan bernomor. Dijaga di layar (`required`) dan di layanan, termasuk pada koreksi |
| 13 | **Pengelolaan pengguna & setelan operasional** | **Super Admin saja** | Menambah, mengubah, dan menonaktifkan pengguna serta mengubah lima parameter operasional dipindahkan dari Admin ke Super Admin. Admin tetap melihat nilai setelan yang berlaku — ia perlu tahu batasnya — tetapi tidak mengubahnya. Pengecualian pintu darurat tetap berlaku untuk membuat Super Admin pertama dan memulihkan bila satu-satunya hilang |
| 14 | **Halaman jejak audit** | **Ada, Super Admin saja** | Sebelumnya jejak tercatat lengkap tetapi tidak punya layar. Sekarang bisa disaring per tanggal, aksi, pelaku, dan pencarian bebas; nilai sebelum/sesudah diurai menjadi baris yang terbaca, bukan JSON mentah. Alasannya di §10 |
| 5 | **Unit printer** | Pilihan B — printer jaringan 80 mm | Tinggal pembelian: lolos tes cetak dari iPhone di toko, lalu pastikan WiFi pos menjangkau printer. Kandidat & daftar periksa di 11.2 |

Aturan komoditas hidup di tabel `timbangan_jenis` dan disalin ke tiap transaksi
saat disimpan — merevisi salah satu keputusan di atas tidak akan pernah
mengubah status transaksi yang sudah tercatat.

Yang masih usulan penyusun dan belum pernah dipakai memutuskan apa pun: ambang
deteksi pola dan bobot skor pemasok (`logic.py`, ditandai NEEDS CONFIRMATION).
Keduanya hanya memberi peringkat pada halaman monitoring, tidak menentukan
status transaksi.

## 13. Rencana Kerja

| Tahap | Isi | Status |
|---|---|---|
| 1 | Arsitektur & rancangan | ✅ dokumen ini |
| 2 | Desain 27 layar | ✅ kanvas |
| 3 | Draf SOP gabah kering & revisi pasal PK | ✅ menunggu tinjauan |
| 4 | Skema DB + migrasi Alembic | ✅ 13 tabel, `0022`–`0024` |
| 5 | Logika bisnis per mode + uji tiga contoh resmi | ✅ `logic.py` |
| 6 | Autentikasi, peran, sesi | ✅ sesi sampai Keluar |
| 7 | Rute & template | ✅ 18 halaman |
| 8 | Lapisan offline: penanda luring, antrean kirim, service worker | ✅ |
| 9 | Halaman cetak thermal 72 mm (AirPrint/Mopria) | ✅ |
| 10 | Ringkasan, monitoring, ekspor CSV | ✅ |
| 11 | Penyemaian master komoditas & akun admin awal | ✅ saat service menyala |
| 12 | Service Railway kedua (`timbangan`), entrypoint tanpa migrasi | ✅ berkas siap, lihat `DEPLOY.md` |
| 13 | Uji di produksi bersama petugas | ⏸ menunggu deploy |

Yang dijaga uji otomatis (170 uji): tiga contoh resmi, matriks aturan per
komoditas, kesepadanan model ⇄ migrasi, idempotensi kiriman ulang, arah barang
menentukan angka bermuatan, tanggal mengikuti timbang kedua, kerahasiaan
selisih pada bukti gabah, dan **ketiadaan kolom maupun kata "harga" di seluruh
modul** — dari tabel database sampai layar dan berkas ekspor.

### Integrasi lanjutan

1. **Kledo** — sinkronisasi kontak supplier lewat `kledo_contact_id`
2. **Modul pabrik** — gabah ke `purchase_batches` (berat nota), PK ke `pk_purchase_batches` (PK bersih)
3. **Agen AI** — bundel tool `timbangan` pada agen yang sudah ada: baca transaksi, tiket terbuka, skor, pola; usulan koreksi lewat gerbang persetujuan. Bukan bot baru
4. **Notifikasi** — tiket menunggak, pemeriksaan belum ditutup, tara jatuh tempo, dikirim lewat poller Telegram yang sudah berjalan

---

*Dokumen ini acuan pembangunan. Seluruh keputusan pada bagian 12 sudah
ditetapkan dan berjalan di produksi sejak 30 Agustus 2026.*
