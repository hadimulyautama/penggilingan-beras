---
name: rancang-ulang-2026
description: "ADR — Satu Pabrik Satu Sistem (13 Sep 2026): USULAN satu produk dua layanan (hmu-app + hmu-agent), satu chain migrasi, TUJUH modul berbatas (Gudang 2 = tahap kedua modul produksi, bukan modul sendiri); belum diputuskan pemilik."
metadata:
  type: project
---

# Catatan keputusan arsitektur — rancang ulang 2026

**Status: DIUSULKAN, belum diputuskan.** Ditulis 13 September 2026 sebagai
Tahap 0 dari `QA/RANCANGAN-untuk-claude-code.md`, menerjemahkan artifact
"Satu Pabrik Satu Sistem" jadi catatan yang bisa ditinjau. Tak ada kode
yang dipindahkan dan tak ada skema yang diubah oleh tahap ini. Peta batas
hari ini ada di `docs/BATAS-MODUL.md`; keduanya dibaca bersama.

## 1. Konteks — apa yang dipisah hari ini, dan kenapa

Satu pabrik, satu PostgreSQL di Railway, **tujuh repo** di workspace
`Hadi Mulya Systems/`:

| Repo | Baris (py+html+js+css) | Bentuk jalan | Tabel yang ditulis |
|---|---|---|---|
| `produksi/` | 42.518 | FastAPI, layar operator Gudang 1 + seluruh layanan pabrik + API internal | 55 tabel pabrik & master |
| `timbangan/` | 25.282 | FastAPI PWA pos timbang | 15 `timbangan_*` |
| `kantor/` | 16.057 | bot Telegram long-polling + 8 poller + LLM | 15 `kantor_*` (+ `suppliers` lewat sinkron Kledo) |
| `meja/` | 6.305 | klien tipis di atas API produksi | — (tak punya tabel) |
| `gudang2/` | 5.177 | klien tipis di atas API produksi | — (tak punya tabel) |
| `core/` | 402 | paket `hmu_core`: 6 model master | — (chain-nya tak punya pelari) |
| `website/` | 5.107 | Flask situs perusahaan | — (basis data lain / tidak ada) |

Pemisahannya terjadi bertahap dan tiap langkahnya punya alasan yang
tercatat (`docs/ingatan/pisah-kantor-produksi.md`, `timbangan-module.md`,
`gudang2/docs/RANCANGAN.md`, `meja/docs/RANCANGAN.md`):

- **31 Agustus** — Timbangan keluar: satu push ke repo produksi dulu
  mendeploy ulang tiga service sekaligus; perbaikan kecil di pos timbang
  harus menunggu rilis penggilingan.
- **2 September** — Kantor keluar: bot yang mati tak boleh menyeret layar
  pabrik; anggaran LLM dan kill-switch butuh rumah sendiri. Skema master
  jadi paket `hmu_core` (submodule di kantor, vendored di produksi).
- **12 September** — Gudang 2 dan Meja lahir sebagai repo sendiri, lalu
  pada hari yang sama diputuskan **tipis**: "semua tidak punya tabel,
  database dipakai bersama, agar semuanya terintegrasi". Keduanya membaca
  `/internal/*` dan menulis `/miniapp/*` di produksi atas nama akun
  `produksi_akun` yang sama.

Yang dicapai: kemandirian rilis. Yang tidak berubah: **datanya satu**. Dari
76 tabel di basis data, 76 dibuat oleh chain migrasi produksi — termasuk 15
`kantor_*` (0016–0021) dan 15 `timbangan_*` (0022–0026) yang kini "dimiliki"
repo lain lewat tabel versi terpisah (`alembic_version_kantor`,
`alembic_version_timbangan`; `alembic_version_core` hanya di-stamp).

## 2. Masalah yang terbukti (bukan yang ditakutkan)

Tiga putaran QA independen: 123 + 143 + 16 = 282 butir laporan (159
temuan unik menurut rapor putaran 3). Yang menentukan arah rancangan
adalah yang lahir **di sambungan antar-repo**, bukan di dalam satu repo:

| ID | Yang terjadi | Akar | Keadaan 13 Sep |
|---|---|---|---|
| **X-01** | `reset_data.sql` men-TRUNCATE … CASCADE 72 tabel: tiket timbang, seluruh `kantor_*` (termasuk kill-switch biaya LLM), `produksi_akun`, dan 3 tabel versi migrasi jadi 0 baris | satu basis data, tujuh penulis, tak ada daftar pemilik tabel yang bisa dibaca skrip | ditutup (12 Sep) — tetapi daftar pemiliknya baru ada sekarang, di BATAS-MODUL.md |
| **X-02 · X-12** | basis data kosong tak bisa dibangun dengan urutan yang tertulis ("core dulu" gagal DuplicateTable); `alembic check` mengusulkan DROP 71 tabel | lima chain migrasi di satu skema, tiga di antaranya membuat tabel yang sama | ditutup lewat `scripts/bangun_skema.sh` + `include_object` — jalan, tapi urutannya empat langkah yang harus diingat |
| **X-15** | migrasi core tak punya pelari; tabel master punya dua pemilik | pemilik di atas kertas (core) ≠ pelari (produksi) | terbuka (ARSITEKTUR §4.3) |
| **X-07 · X-08 · X-13** | tiket timbang di-void, pemasok dikoreksi, komoditas diganti — batch produksi tak pernah tahu; satu tiket jadi batch gabah DAN PK | kontrak antar-aplikasi hidup di kueri, tanpa pemilik dan tanpa uji dua sisi | X-07/X-08 ditutup 12 Sep; X-13 dijaga UNIQUE per tabel, belum satu tabel tautan |
| **X-11 · P-S-05 · T-19 · R-P-01** | menonaktifkan orang di produksi tak memutus Kantor & Timbangan; sesi tak bisa dicabut; rute yang menaikkan `token_version` malah 500 | tiga bendera status (`users.status`, `produksi_akun.status`, `timbangan_akun.status`), dua tabel akun dengan aturan sesi berbeda | sebagian: ketiga app memeriksa `users.status`, tapi tak ada rute yang menyetelnya |
| **X-22** | `app.css` 1.360 baris, `aksi.js` 877, `pindah.js` 473, `base.html`, `_benda.html` disalin ke tiga repo; dua penyesuaian (deep-link `aksi.js:835`, pembungkus `_benda.html:164`) hidup **hanya** di salinan padahal CLAUDE.md melarang menyunting salinan | tampilan bukan paket, melainkan berkas yang disalin | terbuka; produksi sendiri masih memuat R-P-10 yang salinannya sudah menambal |
| **X-23 · M-03** | Meja mati total saat produksi mati; dokumen menyebut "mockup" sementara tombolnya menulis sungguhan ke `packaging_purchases` | pemisahan proses tanpa pemisahan ketergantungan; dokumen tertinggal dari keputusan | X-23 kini berlaku juga untuk gudang2 (RANCANGAN §9 gudang2 mencatatnya) |
| **X-24** | chain migrasi gudang2 & meja belum ada | — | gugur: keduanya diputuskan tanpa tabel |
| **P-K-01 · P-K-08 · P-K-10 · P-K-21** | kode harian macet sesudah Undo; undo menghapus baris orang lain; undo intake PK membuat silo −7.000 kg; undo menghapus jejak audit | pencatatan menimpa angka dan menghapus baris; stok yang dihitung dari pergerakan justru yang jarang salah | P-K-01/08/21 ditutup (penghitung atomik, log_id, jejak ditandai); P-K-10 masih terbuka |
| **T-01 · P-K-04 · P-K-05 · P-K-06** | nomor tiket kembar 16/16, PK masuk dua kali 20/20, satu lot di dua silo 10/10, transfer melebihi hasil giling | baca-lalu-tulis tanpa kunci baris, tanpa constraint | ditutup satu per satu dengan FOR UPDATE + indeks unik |
| **K-01 · K-09 · K-10** | alat Drive tanpa gerbang; `admin` pabrik = kuasa penuh Kantor; penjaga biaya meremehkan 8,6× dan gagal-terbuka, batasnya dibagi dengan produksi | peran kasar bersama dipakai sebagai izin alat; guard biaya punya dua salinan kode atas satu tabel | K-01 ditutup; K-09, K-10 terbuka |

Pola yang muncul: hampir semua yang mahal adalah **pekerjaan di sambungan**
— dan sambungannya tidak hilang dengan memisah repo, karena datanya tetap
satu. Yang dipisah adalah kodenya; yang menyatukan adalah datanya; dan di
situlah semua lukanya.

Ukuran biaya yang dibayar tiap hari, per 13 September:

- **4 salinan aset tampilan** (produksi, gudang2, meja; timbangan punya
  CSS-nya sendiri dengan token yang berbeda — ARSITEKTUR §9).
- **4 chain migrasi aktif** + 1 yang hanya di-stamp; bootstrap DB kosong =
  4 langkah berurutan.
- **3 tabel akun/identitas** (`users`, `produksi_akun`, `timbangan_akun`)
  dan **3 himpunan peran** yang harus disapu tiap kali peran bertambah
  (sembilan kali tertinggal di gerbang yang menyebut nama — `peran-superadmin-tuntas.md`).
- **2 kontrak HTTP internal** tanpa uji dua sisi (`/internal/produksi/*`
  untuk Kantor; `/internal/meja/*` + `/internal/gudang2/*` + `/miniapp/*`
  untuk Meja & Gudang 2), dengan konsekuensi "produksi mati = tiga layar mati".
- **2 salinan `guard.py`** biaya LLM atas satu tabel `kantor_llm_usage`.

## 3. Opsi yang dipertimbangkan

### A. Tetap tujuh repo, rapikan sambungannya

Teruskan arah sekarang: paket tampilan bersama, paket identitas bersama,
uji kontrak untuk tiap `/internal/*`, dokumen pemilik tabel.

- *Untung:* tak ada pemindahan kode; kemandirian rilis tetap; risiko nol
  terhadap sistem yang sedang berjalan.
- *Rugi:* sambungan HTTP tetap ada dan tetap harus diuji dua sisi; Meja dan
  Gudang 2 tetap mati bersama produksi; lima chain migrasi tetap lima;
  setiap aturan lintas modul (tiket void → batch) tetap dua deploy.
- *Untuk siapa ini benar:* tim yang lebih dari satu orang dan merilis
  sendiri-sendiri. Hari ini timnya satu orang dengan Claude Code.

### B. Satu aplikasi tunggal, tanpa batas modul

Gabungkan semuanya (termasuk bot Kantor & poller) ke satu proses dan satu
repo, seperti keadaan sebelum 31 Agustus.

- *Untung:* paling sedikit lapisan; satu deploy; satu sesi.
- *Rugi:* persis alasan Kantor dulu dikeluarkan — bot yang mati menyeret
  layar pos timbang; anggaran LLM dan kill-switch tak punya rumah yang
  bisa dimatikan sendiri; long-polling menuntut satu replika sementara
  layar boleh N replika; 66.000+ baris tanpa batas akan saling impor
  sembarangan (jerat `ai → kantor → ai` yang dulu memakan satu hari).

### C. Satu produk, dua layanan, modul berbatas — **yang diusulkan**

- **`hmu-app`**: satu proses FastAPI, N replika, tanpa status; memuat
  ruang kerja Pos Timbang, Gudang 1, Gudang 2, Meja sebagai modul berbatas
  dengan pintu masuk resmi (`layanan.py`) dan awalan nama tabel.
- **`hmu-agent`**: Kantor AI tetap layanan sendiri — bot long-polling,
  poller dengan kunci advisory, anggaran LLM sendiri, satu replika —
  tetapi memakai paket modul yang sama di dalam prosesnya, bukan HTTP.
- **Satu chain migrasi**, satu pemilik skema, satu bootstrap satu perintah.
- **Tulang punggung peristiwa**: buku besar tambah-saja + proyeksi
  terhitung; pembatalan = peristiwa lawan; tak ada DELETE pada baris bisnis.
- **Layar tetap terpisah** menurut peran & tempat kerja: alamat, ikon, dan
  menu tiap ruang kerja tidak berubah bagi yang memakainya.
- Situs perusahaan tetap terpisah (tak ada data pabrik).

Alasan memilih C atas A: biaya A dibayar setiap hari dan manfaatnya belum
ada yang memungut. Alasan memilih C atas B: bentuk jalan yang berbeda
(long-polling 24 jam, anggaran, satu replika) adalah alasan sah untuk
layanan sendiri; peran yang berbeda bukan.

Satu hal yang membuat C lebih murah daripada kelihatannya: **Meja dan
Gudang 2 sudah tipis.** Keduanya tak punya tabel dan tak punya aturan;
memasukkannya ke `hmu-app` berarti mengganti `klien.py` dengan panggilan
fungsi dan membuang satu sesi cookie — bukan memindahkan data.

## 4. Keputusan yang DIUSULKAN

Opsi **C**, dikerjakan menurut tahapan `QA/RANCANGAN-untuk-claude-code.md`:
Tahap 1 (paket tampilan) dan Tahap 2 (satu identitas) **aman dikerjakan
apa pun keputusan akhirnya** — keduanya menutup X-22 dan X-11 bahkan bila
tujuh repo dipertahankan. Tahap 3 (peristiwa), 4 (modul masuk), 5 (agen)
menunggu persetujuan pemilik dan dikerjakan satu modul per sesi.

Peta **tujuh** modul dan pemetaan 76 tabel ke dalamnya ada di
`docs/BATAS-MODUL.md` §4 — berikut tabel yang tak jelas pemiliknya, yang
sengaja tidak diputuskan di sini.

### 4.1 Gudang 2 ADALAH produksi — pemeriksaan teknis

Koreksi pemilik (13 September, siang): usulan awal memisahkan "Gudang 1"
dan "Gudang 2" sebagai dua modul. Itu keliru. Repo `produksi/` hari ini
sebenarnya hanya Gudang 1 (selepan) ditambah seluruh layanan pabrik; repo
`gudang2/` adalah TAHAP KEDUA dari aliran barang yang sama: gabah masuk →
pengeringan → silo → giling → PK → transfer → penyosohan → beras & hasil
samping. Diminta memeriksa apakah ada alasan teknis yang membantahnya.

**Tidak ada. Buktinya justru sebaliknya — kodenya sudah satu, hanya
namanya yang dua:**

- Kode Gudang 2 tidak pernah keluar dari repo produksi. `app/penggilingan/
  gudang2/` (service, polishing, models) ada di `produksi/`; repo `gudang2/`
  tak punya tabel dan tak punya aturan — ia menggambar `/internal/gudang2/*`.
- Transfer PK adalah satu jalur kode yang menyeberang "batas" itu di dalam
  satu proses: `app/services/transfer.py:182-184` mengimpor dan memanggil
  `gudang2.service._add_intake` langsung. Di arah sebaliknya
  `gudang2/service.py:42-43` mengimpor `find_or_create_supplier` dan
  `timbang_link` milik gudang1. Dua modul yang saling mengimpor internal
  bukan dua modul; itu satu modul dengan dua folder.
- Tabel jahitannya (`internal_transfers`, `pk_gudang2_intakes`,
  `pk_purchase_batches`, `polishing_*`, `silo_storage`/`silos` Gudang 2)
  ditulis dan dibaca dari kedua "sisi" — BATAS-MODUL §3.
- Empat temuan lahir tepat di jahitan itu, dan semuanya adalah jenis
  kesalahan yang muncul ketika satu aliran diperlakukan sebagai dua sistem
  yang harus dicocokkan: **P-K-04** (PK luar masuk G2 dua kali, 20/20),
  **P-K-06** (transfer melebihi hasil giling — 6 t jadi 12 t di G2, G1
  menampilkan 0), **P-K-11** (silo G2 menerima PK saat dipoles, 12 t vs
  fisik 7 t), **P-K-20** (PK di tumpukan G2 tak punya jalan ke silo —
  fungsinya ada di kode, pintunya tak ada di layar mana pun).
- Ketelusuran beras putih ke gabahnya (syarat pemilik 4 September,
  `ketelusuran-hulu-hilir.md`) menuntut satu rantai LOT → TRF → intake →
  POL yang dibaca sebagai satu aliran; ia putus persis di transfer bila
  transfer diperlakukan sebagai jahitan antar-sistem.

Satu-satunya hal yang membedakan kedua gudang secara teknis adalah DATA:
baris `warehouses` yang berbeda, silo yang berbeda, dan operator yang
ruang lingkupnya berbeda (identitas). Itu urusan ruang kerja & ruang
lingkup, bukan batas modul. Maka modul `produksi` memuat kedua tahap;
"Gudang 1"/"Gudang 2" tinggal sebagai nama layar (ruang kerja) dan nilai
kolom, dan Tahap 4 untuk `gudang2` berarti **menyatu ke produksi**, bukan
masuk sebagai modul sendiri — dengan pembuktian ulang r01/r03 tetap 0/20.

## 5. Konsekuensi yang diterima

- **Rilis jadi satu untuk semua layar.** Memperbaiki satu tombol Meja
  berarti menerbitkan ulang `hmu-app`. Mitigasi: rilis kecil & sering,
  `/health` yang menolak menyala di atas skema yang salah (sudah ada, X-04),
  dan uji rute per layar. Bagi satu orang yang merilis beberapa kali
  sehari ini lebih murah daripada menyalin perbaikan tiga kali.
- **Satu migrasi buruk mengenai semuanya.** Sudah begitu sekarang — basis
  datanya satu; yang berubah pintu masuknya dari lima jadi satu.
- **Repo jadi besar (±100.000 baris termasuk templat).** Menuntut batas
  modul yang DITEGAKKAN uji: awalan tabel, larangan impor lintas modul
  selain lewat `layanan.py`, larangan menyentuh tabel tetangga.
- **Timbangan tetap tanpa kolom harga** — batas modul menggantikan batas
  repo untuk kerahasiaan itu; ujinya (pemindai kata uang) ikut pindah.
- **Selama peralihan ada dua jalan ke satu pekerjaan** (aplikasi lama +
  modul baru). Aturan: aplikasi lama tetap hidup sampai penggantinya
  terbukti; satu rilis pindahan per modul.
- **Sejarah migrasi 0001–0046 tidak ditulis ulang.** Penggabungan chain
  berarti mengakui riwayat yang sudah jalan di server (stamp), bukan
  membangun ulang; migrasi core 0001/0003/0029 yang tumpang tindih
  dinetralkan dengan dinyatakan, bukan dihapus.

## 6. Yang akan membalikkan keputusan ini

- **Tim kedua** yang bertanggung jawab penuh atas satu bagian (mis. Kantor
  AI) dan merilis sendiri — pemisahan repo jadi masuk akal lagi. Modul
  yang sudah berbatas bisa dipotong keluar; yang saling memanggil
  sembarangan tidak. Jadi C tidak menutup jalan kembali ke A.
- **Pabrik kedua dengan operasi terpisah** yang menuntut pemasangan
  sebagian (hanya pos timbang, misalnya). C menjawabnya dengan modul yang
  dimatikan lewat setelan; bila itu terbukti tidak cukup, pemisahan proses
  per modul kembali dipertimbangkan.
- **Bukti bahwa satu proses tidak sanggup**: layar pabrik terganggu oleh
  beban Meja/laporan yang berat (R-P-04: 3.795 kueri per halaman Direksi).
  Jawaban pertamanya proyeksi & replika, bukan pemisahan.
- **Tahap 3 gagal memenuhi janjinya**: bila satu aksi di jalur peristiwa
  ternyata jauh lebih rumit atau lebih lambat tanpa menutup P-K-10, tulang
  punggungnya dihentikan di satu aksi dan sisanya tetap di jalur lama.

## 7. Pertanyaan terbuka — butuh keputusan pemilik

1. **Arah:** A, B, atau C? Tahap 1–2 bisa berjalan sebelum ini dijawab.
2. **Nama tabel:** mengganti nama 76 tabel ke awalan modul (`g1_*`, `sedia_*`)
   adalah migrasi besar yang menyentuh Kledo/skrip/dokumen; alternatifnya
   awalan hanya untuk tabel BARU dan peta pemilik untuk yang lama. Mana?
3. **Rumah tabel mitra & alat** (`suppliers`, `pelanggan`, `warehouses`,
   `silos`, `dryers`): tujuh modul tak punya tempat untuknya. Modul
   kedelapan `master`, `identitas` diperlebar jadi `pihak`, atau alat masuk
   `produksi` dan mitra masuk `uang`? (BATAS-MODUL §4.8.)
4. **`kantor_config` & `kantor_llm_usage`** dipakai dua guard (produksi &
   kantor). Di C pemiliknya `agen`; tetapi guard biaya produksi (agen
   pabrik, `/internal/produksi/tanya`) juga menulisnya. Satu guard di
   paket bersama, atau dua anggaran terpisah (K-10 menyarankan terpisah)?
5. **Peran vs izin alat**: `kantor_role`/`kantor_user_role` ke `identitas`,
   `kantor_grant` ke `agen` (K-09)? Atau ketiganya `identitas`?
6. **`setelan_pabrik`, `notifications`, `kode_urut`**: milik proses yang
   mana? Usulan di BATAS-MODUL §4, tetapi ini keputusan.
7. **Verifikasi harga & output** (`purchase_batch_verifications`,
   `pk_purchase_verifications`, `milling_process_verifications`): barisnya
   menempel pada proses fisik (produksi) tetapi isinya rupiah (uang). Satu
   tabel dua modul, atau dipecah?
8. **Migrasi akun timbangan** ke identitas bersama (Tahap 2 butir 4):
   dijalankan saat pos timbang tutup, atau dengan dua tabel hidup
   berdampingan selama satu minggu?
9. **Branch `gudang2-api` produksi** (aturan silo Gudang 2, migrasi 0046)
   belum digabung ke `main`. Tahap 3–4 akan membangun di atasnya —
   digabung dulu, atau ditunggu?
