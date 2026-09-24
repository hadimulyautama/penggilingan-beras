# Arsitektur Sistem — PT Hadi Mulya Utama

> **24 September 2026 — app Meja & app Gudang 2 DIHAPUS.** Keputusan pemilik:
> keduanya tidak dipakai lagi; operator Gudang 2 maupun staf administrasi
> memakai Pos Produksi. Layanan Railway, repo GitHub, dan folder lokalnya
> dihapus (riwayatnya tersimpan sebagai bundel git di `../arsip/`), dan pintu
> `/internal/meja/*` serta `/internal/gudang2/*` berikut `MEJA_API_TOKEN`
> dicabut dari produksi. **Setiap kalimat di bawah yang menyebut kedua app itu
> harus dibaca sebagai riwayat, bukan keadaan sekarang.**


**Peta tingkat sistem: tiga sistem, tiga repo, satu database**
Versi 1.4 · 2 September 2026

Dokumen ini menjelaskan bagaimana ketiga modul berdiri, apa yang dipakai bersama, dan aturan yang menjaga agar penambahan modul berikutnya tidak merusak yang sudah ada. Rancangan rinci tiap modul ada di dokumennya sendiri.

---

## 1. Tiga modul

| Modul | Untuk siapa | Isi | Di kode |
|---|---|---|---|
| **Produksi penggilingan** | Operator gudang & staff | Gabah masuk, pengeringan, silo, milling, penyosohan, barang jadi, kemasan, barang keluar | `app/penggilingan/` |
| **Kantor AI (agen asisten)** | Direksi & manajer | Arsip Drive, Gmail, Kledo, GajiHub, IT aset, pengetahuan, persetujuan, lapisan proaktif | **repo terpisah:** [`hadimulyautama/kantor`](https://github.com/hadimulyautama/kantor) |
| **Timbangan** | Petugas pos timbang | Catat timbang, kontrol terhadap nota & surat jalan, monitoring | **repo terpisah:** [`hadimulyautama/timbangan`](https://github.com/hadimulyautama/timbangan) |

> **Timbangan pindah repo pada 31 Agustus 2026.** Alasannya kemandirian
> rilis: satu push ke repo ini dulu mendeploy ulang ketiga service, sehingga
> perbaikan kecil di pos timbang harus menunggu — dan ikut memicu — rilis
> penggilingan dan Kantor AI. Databasenya **tetap satu**; yang dipisah
> kodenya, bukan datanya.
>
> Empat foreign key masih menyeberang: `timbangan_akun.user_id` → `users`,
> `timbangan_transaksi.supplier_id` → `suppliers`, `.purchase_batch_id` →
> `purchase_batches`, `.pk_purchase_batch_id` → `pk_purchase_batches`.
> Keempat tabel itu milik repo ini. **Mengubah bentuknya bisa merusak pos
> timbang, dan tidak ada lagi satu rangkaian uji yang menangkapnya** —
> kontraknya ditulis di `app/models.py` repo sebelah.
>
> Migrasi `0022`–`0026` di repo ini adalah riwayat yang sudah diterapkan dan
> **tetap tinggal** — riwayat migrasi hanya bertambah, sama seperti jejak
> audit. Migrasi timbangan berikutnya ditulis di repo sebelah, dengan tabel
> versi `alembic_version_timbangan` yang terpisah dari `alembic_version`
> milik repo ini.

### Tiga sistem, tiga repo — dan bagaimana yang terakhir dilepas

**Kantor AI pindah repo pada 2 September 2026**, menyusul timbangan. Ketiganya
kini berdiri sendiri, dengan **satu database** yang sama.

Timbangan dulu mudah pergi: ia hanya **menyentuh** fondasi — mengimpor `config`,
`database`, `models`, dan tak satu pun modul lain mengimpornya.

Kantor tidak begitu. Ia **dilingkari** fondasi: fondasinya sendiri bergantung
padanya, dan lingkaran `ai → kantor → ai` itulah yang selama ini menahannya.
Empat simpul dipotong, dan cara memotongnya perlu dicatat karena polanya bisa
dipakai lagi:

| Simpul lama | Cara dipotong |
|---|---|
| `ai/guard.py` → `kantor.models` (tabel `kantor_config`, `kantor_llm_usage`) | Definisi kedua tabel pindah ke **`app/ai/models.py`** — guard biaya adalah urusan fondasi. Nama tabel tidak berubah, jadi tanpa migrasi apa pun. |
| `models` (fasad) → `kantor.models` | Fasad tak lagi mendaftarkan tabel Kantor; chain migrasi Kantor yang memilikinya. |
| `bots/registry` → `kantor.bot` | Router Kantor dicabut; token botnya pindah ke service sendiri. |
| `kantor` → `ai.agent`, `services.analytics`, `services.dashboard` | Diganti **API internal** produksi (`/internal/produksi/*`) yang dipanggil `klien_produksi` di repo Kantor. |

Satu jerat tersembunyi ikut dilepas: `bots/common.py` mengimpor tipe dari
`ai/nlp_parser`, yang menyeret NLP domain pabrik. Karena berkas itu memakai
`from __future__ import annotations`, anotasinya tak pernah dievaluasi runtime —
impornya cukup dipindah ke blok `TYPE_CHECKING`, dan Kantor bisa memakai helper
generiknya tanpa menarik kode penggilingan.

Service **`mcp`** — read-only tools untuk agen luar (Hermes/Cowork) — **dipensiunkan
pada hari yang sama**: pemiliknya tak lagi memakai Hermes, dan lognya tak pernah
mencatat satu pun permintaan nyata. Kodenya tinggal di riwayat git.

**Skema master pindah ke paket bersama `hmu_core`** (repo
[`hadimulyautama/hmu-core`](https://github.com/hadimulyautama/hmu-core)): `Base`,
`TimestampMixin`, dan enam model master (`users`, `warehouses`, `suppliers`,
`pelanggan`, `silos`, `dryers`). Kantor memakainya sebagai submodule `core/`;
repo ini menyalinnya (vendored) ke `hmu_core/`.

### Membaca susunan berkasnya

```
app/
  config.py  database.py  main.py  seed.py     ← fondasi
  models/                                       ← fasad model domain pabrik
  ai/                                           ← lapisan agentik (agen, guard, tool pabrik)
  bots/  services/  web/                        ← kerangka bot + layanan penggilingan
  penggilingan/   gudang1  gudang2  inventory
  web/internal.py                               ← API internal: satu-satunya pintu Kantor
hmu_core/                                       ← salinan skema master (paket bersama)
```

Setelah Kantor keluar, hampir semua isi repo ini melayani penggilingan. Dua
catatan yang tersisa:

- **`app/ai/` tetap bukan milik penggilingan sepenuhnya.** Isinya sekarang
  terbelah jelas: `guard`, `models`, `claude_client`, `tanggal` adalah fondasi
  (Kantor punya salinannya sendiri), sedangkan `agent`, `tools`, `nlp_parser`,
  `base`, `router`, `fast_route` adalah tool & prompt PABRIK.
- **`app/bots/` akan ikut hilang pada Fase B**, saat produksi berubah jadi
  webapp tanpa bot. Kantor sudah tidak bergantung padanya.

Modul adalah **bidang kerja**, bukan proses. Satu modul boleh berjalan di service mana pun; yang membuatnya modul adalah batas tanggung jawab dan batas tabelnya.

---

## 2. Fondasi bersama

Satu-satunya hal yang benar-benar dipakai bersama, dan karenanya tidak boleh diduplikasi:

| Fondasi | Tabel / berkas | Aturan |
|---|---|---|
| **Database** | Satu PostgreSQL di Railway | Semua modul menunjuk `DATABASE_URL` yang sama |
| **Identitas orang** | `users` | Tidak ada master pengguna kedua. Modul boleh menambah tabel kredensial sendiri yang menaut ke sini (`timbangan_akun.user_id`) |
| **Identitas mitra** | `suppliers` | Sumber tunggal supplier & pihak. `kledo_contact_id` disiapkan untuk sinkronisasi Kledo |
| **Hak akses** | `kantor_role`, `kantor_user_role`, `kantor_grant` | Grant `domain → none/read/write/owner`, union antar-peran, ditegakkan di kode |
| **Jejak audit** | `activity_logs`, `kantor_audit_log`, `timbangan_audit` | Hanya bertambah, tidak pernah ditimpa |
| **Guard biaya LLM** | `kantor_config`, `kantor_llm_usage` via `app/ai/models.py` + `app/ai/guard.py` (kedua repo punya salinan guard-nya; tabelnya bersama) | **Setiap** panggilan LLM lewat sini: kill-switch, batas bulanan, pencatatan token |
| **Notifikasi** | Bot Telegram + poller | Modul mengirim lewat bot yang sudah ada, tidak membuat bot baru |

> **Prinsip:** fungsi baru menambah kemampuan pada bot dan agen yang ada — **bukan bot baru**. Tiap bot baru berarti token baru, proses baru, dan satu tempat lagi yang bisa mati diam-diam.

---

## 3. Kepemilikan tabel

Tiap tabel dimiliki satu modul. Modul lain boleh **membaca**, tetapi hanya pemilik yang **menulis**.

| Modul | Tabel yang dimiliki |
|---|---|
| Master bersama (paket `hmu_core`) | `users`, `suppliers`, `warehouses`, `pelanggan`, `silos`, `dryers` |
| Produksi | `purchase_batches`, `drying_*`, `silo_*`, `milling_*`, `pk_*`, `polishing_*`, `finished_goods_stocks`, `packaging_*`, `outgoing_*`, `internal_transfers`, `byproduct_*`, `brands`, `product_skus` |
| Kantor AI (repo `kantor`) | 15 tabel `kantor_*`: `kantor_sop_dokumen`, `kantor_sop_chunk`, `kantor_aksi_pending`, `kantor_audit_log`, `kantor_chat_riwayat`, `kantor_aset`, `kantor_kartu_pemeliharaan`, `kantor_nomor_dokumen`, `kantor_aturan_email`, `kantor_heartbeat`, `kantor_config`, `kantor_llm_usage`, `kantor_role`, `kantor_user_role`, `kantor_grant` |
| Timbangan | `timbangan_*` (13 tabel) |

**Modul berbicara lewat database — dengan satu pengecualian yang disengaja.**
Timbangan dan produksi hanya bertemu di tabel. Tetapi Kantor perlu tiga hal yang
tidak ada di tabel mana pun — jawaban agen pabrik, simulasi HPP, dan ringkasan
operasional harian — dan menyalin logikanya berarti dua sumber kebenaran. Untuk
itu, dan **hanya** itu, produksi membuka `/internal/produksi/{tanya,hpp,operasional}`:
read-only, ber-token, dipanggil `klien_produksi` di repo Kantor. Bila produksi mati,
Kantor tetap jalan — hanya fitur pabriknya yang menjawab "tak bisa dihubungi".

**Pengecualian kedua (12 September 2026): Meja Administrasi.** Repo `meja/`
(service `meja`) memegang seluruh pekerjaan staf administrasi kedua gudang
dan TIPIS: tanpa basis data, tanpa logika bisnis. Ia memanggil
`/internal/meja/*` (`app/web/meja_api.py` — bungkus JSON atas layanan
berjalan/stok/audit/undo/setelan/user_admin/alat), serta `/api/*` dan
`/api/laporan/*` yang sudah ada, atas nama akun `produksi_akun` lewat header
`X-Internal-Token` + `X-Meja-Akun` + `X-Meja-Versi` (dikenali
`security.akun_opsional`, pagar CSRF melewatkannya — `csrf.dari_meja`).
Tokennya `MEJA_API_TOKEN`, SENGAJA terpisah dari `INTERNAL_API_TOKEN` Kantor
karena Meja menulis. Layar admin di repo ini dicabut dalam satu rilis
pindahan setelah Meja dipakai (keputusan pemilik); layanan dan API tetap.

Titik temu antar-modul dibuat eksplisit sebagai kolom jembatan, bukan sebagai sambungan diam-diam:

```
timbangan_transaksi.purchase_batch_id     → purchase_batches      (gabah, berat nota)
timbangan_transaksi.pk_purchase_batch_id  → pk_purchase_batches   (PK, berat bersih)
suppliers.kledo_contact_id                → kontak Kledo
timbangan_akun.user_id                    → users
```

### 3.1 Kontrak baca produksi → `timbangan_transaksi`

Produksi **membaca** satu tabel milik Timbangan dan tidak pernah menulis padanya.
Daftar di bawah adalah kontraknya: kolom yang hilang atau berubah artinya akan
memutus intake gabah dan PK luar, dan perubahannya harus disepakati dua repo.

| Kolom | Dipakai produksi untuk |
|---|---|
| `id` | kunci taut — `purchase_batches.timbangan_transaksi_id` (UNIQUE), sama di `pk_purchase_batches` |
| `kode` | nomor tiket yang dibaca orang di layar, log, dan rekonsiliasi |
| `arah` | wajib `MASUK`; tiket KELUAR bukan intake |
| `jenis_kode` | menentukan komoditas lewat `app/penggilingan/peta_jenis.py` (`GABAH_BASAH`, `GABAH_KERING` → gabah; `BERAS_PK` → PK) |
| `status_transaksi` | wajib `AKTIF`. Tiket `VOID` tak ditawarkan, tak bisa jadi batch, dan bobotnya tak disalin |
| `status_tiket` | `DITUTUP_PAKSA` ditolak sebagai sumber batch; `SELESAI`/`TERBUKA` diterima |
| `netto_timbangan_kg` | bobot timbang riil — acuan bila tak ada nota |
| `berat_acuan_kg` | bobot nota/surat jalan; bila > 0, inilah yang dipakai |
| `selisih_kg`, `selisih_persen` | ditampilkan di rekonsiliasi, tidak dihitung ulang produksi |
| `supplier_id`, `pihak_nama` | pemasok batch; `pihak_nama` hanya bila `supplier_id` kosong |
| `nomor_polisi`, `nama_sopir` | ditempelkan ke batch untuk penelusuran |
| `timbang1_waktu` | **waktu kedatangan batch** — bukan jam operator mengetik |
| `tanggal` | urutan di antrean pilihan tiket |

Tiga aturan yang menyertainya:

1. **Nilai `status_transaksi` dan `status_tiket` adalah bagian kontrak**, bukan
   detail internal Timbangan. Produksi membandingkannya sebagai teks
   (`'AKTIF'`, `'DITUTUP_PAKSA'`) di `SYARAT_TIKET_SAH`
   (`app/penggilingan/gudang1/services/timbang_link.py`) — satu tempat, dipakai
   antrean, pengambilan satuan, sinkron, dan rekonsiliasi.
2. **`SELECT … FOR UPDATE` pada `timbangan_transaksi` bukan penulisan.** Saat
   menautkan batch, produksi mengunci baris tiketnya agar dua operator tak bisa
   memakai tiket yang sama di dua tabel batch sekaligus (`UNIQUE` hanya berlaku
   per tabel). Kuncinya dilepas begitu transaksi selesai; tak satu kolom pun
   diubah.
3. **Satu-satunya penulisan yang ada** adalah penyemaian data uji
   (`app/services/data_uji.py`), dan itu menolak berjalan begitu ada tiket
   sungguhan di tabel — tiket karangan pernah muncul di layar petugas timbang.

---

## 4. Topologi Railway

```
   ┌──────────────────────┐  ┌──────────────────┐  ┌────────────────────┐
   │ penggilingan-beras   │  │ kantor           │  │ timbangan          │
   │  FastAPI + mini-app  │  │  bot Kantor      │  │  FastAPI PWA pos   │
   │  3 bot pabrik        │  │  7 poller        │  │  deploy bebas      │
   │  /internal/produksi/*│◄─┤  heartbeat       │  └─────────┬──────────┘
   │  1 replica           │  │  1 replica       │            │
   └──────────┬───────────┘  └────────┬─────────┘            │
              └───────────────────────┴──────────────────────┘
                          Service: PostgreSQL
```

Panah itu satu-satunya sambungan HTTP antar-service: Kantor membaca data pabrik
lewat API internal, bukan lewat impor kode dan bukan lewat kueri langsung.

### Tiga chain migrasi di satu database

Setiap repo memigrasi tabelnya sendiri, dibedakan oleh **version table**:

| Chain | Tabel versi | Milik | Menyentuh |
|---|---|---|---|
| Produksi | `alembic_version` | repo ini | tabel pabrik & `timbangan_*` (riwayat lama) |
| Master | `alembic_version_core` | repo `hmu-core` | 6 tabel master |
| Kantor | `alembic_version_kantor` | repo `kantor` | 15 tabel `kantor_*` |

Dua penjaga supaya ketiganya tidak saling injak:

- `migrations/env.py` di repo ini **menyaring tabel `kantor_*`** lewat
  `include_object` — tanpa itu, autogenerate produksi bisa mengusulkan DROP
  tabel Kantor yang berisi data.
- `env.py` di repo Kantor **mengadopsi skema lama otomatis**: bila tabel
  `kantor_*` sudah ada tapi `alembic_version_kantor` belum, baseline-nya dicap
  (stamp), bukan dijalankan.

### Aturan operasional

| Hal | Aturan | Alasan |
|---|---|---|
| Replica | Service yang memegang bot Telegram **wajib 1 replica** | Long-polling ganda menghasilkan `409 Conflict` |
| Token bot | Satu token = satu proses, selamanya | `BOT_KANTOR_TOKEN` kini HANYA di service `kantor`; mengisinya juga di produksi = bentrok polling |
| Migrasi Alembic | Tiap service memigrasi chain-nya sendiri saat start | Version table terpisah membuatnya aman berjalan paralel |
| Urutan pada DB kosong | **`scripts/bangun_skema.sh`** — lihat §4.1 | Urutan "core dulu" TIDAK jalan (X-02) |
| Uji poller ganda | Nyalakan instance kedua dengan `POLLER_AKTIF=false` | Dua poller aktif = email & invoice diproses dua kali |

### 4.1 Membangun skema dari database KOSONG

**Jangan mulai dari `core`.** Urutan itu tertulis di dokumen ini sampai
11 September 2026 dan tidak pernah jalan: chain produksi juga membuat tabel
master (0001/0003/0029), tabel `kantor_*` (0016–0021), dan tabel
`timbangan_*` (0022–0026). Menjalankan core lebih dulu membuat `warehouses`
dua kali, dan bootstrap berhenti di sana. Temuan QA X-02.

Satu-satunya urutan yang terbukti jalan, kini menjadi skrip resmi
`produksi/scripts/bangun_skema.sh`:

```
1. produksi   alembic upgrade head
2. core       alembic stamp 0001_baseline_master     ← akui, jangan upgrade
3. kantor     alembic upgrade head                   ← env.py-nya mengadopsi
4. timbangan  alembic stamp 0026_timbangan_hapus_pengawas
              alembic upgrade head
```

Langkah 4 tak boleh `stamp head`: yang dibuat produksi berhenti di 0026, dan
stamp sampai HEAD mengaku sudah menjalankan 0027–0029 yang kolomnya tak pernah
ada. Akibatnya setiap kueri tiket gagal sementara `/health` menjawab "ok"
(temuan QA X-03).

Skripnya berpagar: hanya loopback, dan nama database wajib berawalan `uji_`.
Untuk database sungguhan, jalankan keempat perintahnya satu per satu dan baca
keluarannya.

### 4.2 Balapan migrasi saat tiga layanan menyala bersamaan (USULAN)

Railway menyalakan ketiga layanan bersamaan. Pada database yang SUDAH terisi
itu aman — tiap chain punya tabel versinya sendiri. Pada database KOSONG tidak:
ketiganya berlomba membuat tabel yang sama, dan yang kalah gagal di
`CREATE TABLE` lalu (sejak X-04) berhenti.

Usulan, belum dikerjakan karena ia menyentuh ketiga `env.py` sekaligus:

```python
# di do_run_migrations, sebelum context.run_migrations()
connection.exec_driver_sql("SELECT pg_advisory_xact_lock(982451653)")
```

Satu angka yang sama untuk ketiga repo. Advisory lock tingkat transaksi
dilepas sendiri saat transaksinya selesai — termasuk bila prosesnya mati — jadi
tak ada kunci yang tertinggal. Yang kedua dan ketiga menunggu, lalu menemukan
tabel versinya sudah ada dan bekerja seperti biasa.

Yang perlu diputuskan sebelum mengerjakannya: apakah timbangan ikut, mengingat
ia memakai `scripts/siapkan_skema.py` dan bukan `alembic upgrade` langsung.

### 4.3 Siapa yang memiliki skema MASTER (USULAN — menunggu keputusan)

Hari ini `users`, `suppliers`, `warehouses`, `pelanggan`, `silos`, dan `dryers`
dimiliki paket `core` di atas kertas, tetapi:

- tak ada satu layanan pun yang menjalankan migrasi core — image kantor bahkan
  tidak menyalin `core/migrations`;
- chain produksi masih membuat DAN mengubah tabel master (0001/0003/0029).

Jadi pemiliknya `core` dan pelarinya produksi. Selama produksi selalu
di-deploy lebih dulu itu berjalan, tetapi ia berjalan karena kebiasaan, bukan
karena aturan. Temuan QA X-15.

Dua pilihan, dan keduanya perlu persetujuan pemilik sebelum dikerjakan:

1. **Produksi jadi pemilik resmi skema master.** Paling sedikit berubah —
   cukup menuliskan yang sudah terjadi. Kerugiannya: `core` berhenti berarti
   sebagai batas, dan repo lain kehilangan satu tempat untuk membaca bentuk
   tabel master.
2. **Core jadi pemilik DAN pelari.** Satu layanan (produksi) menjalankan
   `core upgrade head` lebih dulu, lalu chain-nya sendiri. Lebih bersih, tetapi
   menuntut migrasi produksi 0001/0003/0029 dipindahkan atau dinetralkan —
   dan itu menyentuh sejarah yang sudah berjalan di server.

## 5. Agen adalah konfigurasi, bukan proses

Satu loop agen per sistem, banyak bundel tool per domain. Menambah kemampuan
berarti menambah **bundel tool**, bukan menambah agen atau bot.

```
  repo ini           ┌── bundel produksi  (stok, HPP, milling, pengeringan)
  app/ai/agent    ───┴── (rencana) bundel timbangan: transaksi, tiket terbuka,
                          skor supplier, pola, tara jatuh tempo

  repo kantor        ┌── arsip · Gmail · Kledo · GajiHub · IT aset · pengetahuan
  app/kantor/agent ──┴── tool `tanya_produksi` → mendelegasikan ke agen di atas
                          lewat /internal/produksi/tanya (bukan menyalin tool-nya)
```

Dua loop, bukan karena kemampuannya berbeda, melainkan karena prosesnya
terpisah. Yang penting dijaga: **Kantor tidak pernah menyalin tool pabrik.**
Pertanyaan produksi didelegasikan ke agen yang memilikinya, supaya tarif dan
datanya cuma punya satu sumber.

Aturan yang berlaku untuk semua bundel, di kedua repo:

1. **Agen membaca, atau mengusulkan.** Aksi tulis tidak pernah dieksekusi agen — diusulkan, dikonfirmasi manusia, lalu dijalankan jalur deterministik yang teruji.
2. **Setiap aksi konsekuensial butuh persetujuan.** Lewat `aksi_pending` dan gerbang konfirmasi.
3. **Semua panggilan LLM lewat `guard.panggil()`.** Tanpa kecuali — itu satu-satunya tempat kill-switch dan batas biaya bekerja.
4. **Hak akses ditegakkan di kode**, tidak pernah hanya di prompt.

---

## 6. Batas yang tidak boleh dilanggar

Berlaku untuk modul mana pun, sekarang maupun yang ditambahkan nanti:

- **Data tidak dihapus permanen.** Yang salah dibatalkan beralasan dan tetap tersimpan.
- **Audit hanya bertambah.** Koreksi menulis baris baru berisi nilai sebelum dan sesudah.
- **Hak akses di kode, bukan di tampilan.** Menyembunyikan menu bukan pengamanan.
- **Tidak ada master tandingan.** Orang dan mitra punya satu sumber kebenaran.
- **Kerahasiaan diwujudkan lewat rancangan.** Operator pos timbang tidak boleh tahu harga, maka modul timbangan tidak punya kolom harga sama sekali — bukan sekadar disembunyikan.
- **Tidak ada bot baru untuk fungsi baru.** Tambahkan ke yang sudah ada.

---

## 7. Dokumen tiap modul

| Modul | Dokumen |
|---|---|
| Timbangan | `docs/` di repo timbangan: RANCANGAN, DEPLOY, desain layar, draf SOP gabah kering & revisi Sistem Tara PK |
| Produksi | `Panduan-Penggilingan-Beras.pdf`, `Sistem_Manajemen_Penggilingan_Beras.docx`, `ERD_Penggilingan_Beras.html` |
| Kantor AI | `docs/` di repo kantor: ARSITEKTUR, TATA-NASKAH-DINAS, SETUP-GOOGLE-DRIVE, PETA-SILANG-ARSIP |
| Deploy | `RAILWAY.md`, `DEPLOY-RAILWAY.md` |
| Pemisahan Kantor↔produksi | `docs/pemisahan-kantor-cutover.md` |

---

## 8. Arah ke depan

1. **Timbangan repo & service sendiri** — ✅ selesai 31 Agustus 2026
2. **Skema master jadi paket bersama `hmu_core`** — ✅ selesai 2 September 2026
3. **Kantor AI repo & service sendiri** — ✅ selesai 2 September 2026
4. **Fase B: produksi jadi webapp tanpa bot.** Buang tiga bot pabrik, kembangkan
   mini-app jadi webapp berdiri sendiri. Ganjalannya satu: mini-app sekarang
   mempercayai identitas Telegram (`require_miniapp_user`); webapp tanpa bot
   butuh login sendiri — pola yang sudah terbukti ada di timbangan.
5. **Jembatan timbangan → produksi**: transaksi terkunci menaut ke batch
   pembelian, menghapus input ganda gabah masuk
6. **Sinkronisasi Kledo** untuk kontak supplier lewat `kledo_contact_id`

*Dokumen ini peta, bukan aturan mati. Bila kenyataan berubah, dokumen ini yang diperbarui lebih dulu — sebelum kodenya menyimpang diam-diam.*

### 8.1 Langkah berikutnya untuk realtime: pg_notify → SSE (USULAN, belum dikerjakan)

Denyut sepuluh detik ke `/api/keadaan` sudah jauh lebih murah daripada
menarik halaman penuh tiap tiga puluh detik: jawabannya 23 byte, halamannya
14 kilobyte. Tetapi ia tetap BERTANYA — dan sebagian besar jawabannya "tidak
ada yang berubah". Enam perangkat di gudang berarti ±2.000 permintaan sia-sia
per hari.

Langkah berikutnya membalik arahnya:

1. **`pg_notify` saat sesuatu tercatat.** Pemicunya sudah ada di satu tempat:
   setiap pencatatan menulis baris `activity_logs`. Satu trigger di tabel itu
   mengirimkan `NOTIFY keadaan, '<gudang>:<id>'` — tanpa satu baris pun
   ditambahkan di aplikasi, jadi jalur yang lupa memberi tahu tidak mungkin
   ada.
2. **Satu pendengar per proses aplikasi**, memegang koneksi `LISTEN` sendiri
   dan meneruskan ke antrean di memori.
3. **`GET /api/aliran` sebagai Server-Sent Events**, satu sambungan
   panjang per perangkat. Perangkat tak lagi bertanya; ia diberi tahu.
   Perubahan terlihat dalam hitungan ratusan milidetik alih-alih sepuluh
   detik, dan lalu lintasnya mendekati nol saat pabrik sedang tenang.

Tiga hal yang harus diputuskan sebelum mengerjakannya, dan justru itu sebabnya
ini belum dikerjakan:

- **Railway memutus sambungan menganggur.** SSE perlu denyut sendiri (komentar
  `:ping` tiap ±25 detik), dan itu mengembalikan sebagian lalu lintas yang
  hendak dihemat — meski tetap jauh lebih kecil.
- **Satu replika.** `LISTEN` per proses aman hari ini karena prosesnya satu.
  Bila kelak lebih dari satu, tiap proses mendengar semuanya — itu benar,
  tetapi perlu disengaja, bukan ditemukan.
- **Jalur mundurnya harus tetap ada.** Denyut sepuluh detik jangan dicabut
  saat SSE dinyalakan; ia yang menyelamatkan perangkat yang sambungan
  panjangnya diputus jaringan gudang tanpa memberi tahu siapa pun.

---

## 9. Token tampilan bersama untuk kedua aplikasi (USULAN — belum dikerjakan)

> **13 September 2026:** bagian di bawah tetap usulan untuk TOKEN (ukuran &
> arti warna) yang bisa dibagi dengan Pos Timbang. Yang SUDAH dikerjakan
> hari itu adalah Tahap 1 rancang ulang: seluruh CSS/JS/templat dasar
> produksi, gudang2, dan meja kini satu paket `hmu_tampilan` (repo
> `tampilan/`), di-vendor + manifest + uji penjaga. Lihat
> `docs/ingatan/rancang-ulang-2026.md`.

Ditulis 12 September 2026 sebagai jawaban atas temuan QA UI-07.

Produksi dan Pos Timbang dipakai orang yang sama, di gudang yang sama, sering
pada hari yang sama. Tetapi keduanya menetapkan ukuran huruf, warna, dan
tinggi sentuhnya sendiri-sendiri — jadi perbaikan UI-04 dan UI-05 di produksi
tidak menyentuh Pos Timbang sama sekali, dan kekeliruan yang sama akan
ditemukan lagi di sana pada QA berikutnya.

Yang diusulkan BUKAN kerangka kerja atau build step. Satu berkas CSS berisi
token, disalin ke kedua repo oleh satu skrip, dengan uji yang menjaga
keduanya tetap sama:

```css
/* hmu-token.css — sumbernya SATU, salinannya dua. */
:root {
  /* Ukuran huruf: tak ada yang di bawah --teks-min. */
  --teks-min:    13px;   /* label, keterangan, satuan          */
  --teks-isi:    15px;   /* teks yang dibaca, bukan dipindai   */
  --teks-angka:  17px;   /* angka yang jadi keputusan          */

  /* Tinggi sentuh: jari, bukan kursor. */
  --sentuh-min:  44px;

  /* Warna semantik — artinya, bukan rupanya. */
  --aman:    …;   /* selesai, dalam batas            */
  --hati:    …;   /* perlu diperiksa, belum mendesak */
  --bahaya:  …;   /* salah, atau tak bisa dilanjutkan */

  /* Kontras teks kerja terhadap latarnya: minimal 7:1, diukur bukan ditebak. */
}
```

Tiga hal yang harus diputuskan sebelum mengerjakannya:

- **Siapa pemiliknya.** Paket `core` sudah ada dan sudah memuat model bersama;
  menaruh CSS di sana mencampur dua jenis hal. Alternatifnya repo keempat yang
  isinya hanya token — kecil, tetapi satu repo lagi untuk dirawat.
- **Cara menyalinnya.** Submodule git menuntut orang ingat memperbaruinya;
  skrip salin menuntut uji yang menangkap salinan yang basi. Yang kedua lebih
  sederhana dan lebih mungkin benar.
- **Kedua aplikasi bertema berbeda.** Pos Timbang terang, produksi gelap (plus
  mode terik). Yang dibagi adalah UKURAN dan ARTI warna; nilai warnanya sendiri
  tetap milik masing-masing.

Sebelum itu diputuskan, angka-angka di atas sudah berlaku di produksi dan bisa
disalin tangan ke Pos Timbang bila ada yang menyentuh CSS-nya.
