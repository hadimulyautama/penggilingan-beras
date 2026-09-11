# Arsitektur Sistem — PT Hadi Mulya Utama

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
| Urutan pada DB kosong | `core` dulu, baru `kantor` | Tabel Kantor menaut ke `users` lewat foreign key |
| Uji poller ganda | Nyalakan instance kedua dengan `POLLER_AKTIF=false` | Dua poller aktif = email & invoice diproses dua kali |

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
