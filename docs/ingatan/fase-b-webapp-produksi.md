---
name: fase-b-webapp-produksi
description: "Fase B B1+B2+B3 SELESAI & LIVE di Railway 2026-09-04. Bot operator DIHAPUS. PWA + perpindahan halaman instan SELESAI 4 Sep. Sisa: ADMIN_SANDI_AWAL blm diset, notifikasi in-app, peran superadmin di data (terkunci Kantor)"
metadata:
  type: project
---

**DESAIN UI: ARAH "PANEL PABRIK" (gelap) — PILIHAN PEMILIK.** Saya ajukan 3 arah sbg kanvas mockup
(A selaras Pos Timbang/hangat, B rambu gudang/kontras tinggi, C panel pabrik/gelap padat status).
Pemilik: "jelek design-nya" → sempat minta ikut timbangan → lalu "salah. ikut design C saja".
Mockup yang ditolak SUDAH DIHAPUS. Sistem nyatanya di `app/web/static/app.css`: satu dunia gelap
(sengaja TIDAK ikut prefers-color-scheme — perangkat dipakai bergantian, tampilan berubah bikin
ragu), IBM Plex Sans+Mono, target sentuh >=56px, identitas pemakai selalu di kepala layar.
Kanvas https://claude.ai/code/artifact/4f50c86d-631a-4a01-ba8a-b6a7119b898d SUDAH DIBERSIHKAN
(2026-09-02): A & B dihapus dari halaman tersimpan — pemilik sempat bingung karena repo sudah
bersih tapi kanvasnya masih memuat arah yang ditolak. Isinya sekarang 3 artboard yang MENCERMINKAN
layar terbangun: Beranda operator, Masuk, Catat pekerjaan. Berkas kerjanya TIDAK disimpan di repo
(sengaja, repo bersih); untuk mengubah kanvas lagi: Artifact action:"read" → `seed-canvas.mjs
--extract <berkas hasil read> --to <dir baru>` → sunting → seed ulang → republish dgn url yang sama,
contract "0.1.31", TANPA capabilities. Terbukti berhasil dipakai.

**LIVE DI RAILWAY 2026-09-04.** `main` = 25 commit di atas 1c22d97; migrasi 0031 & 0032
jalan bersih di DB produksi; VERSI aset 8. **SISA SATU LANGKAH PEMILIK: set
`ADMIN_SANDI_AWAL` di Railway** (SECRET_KEY & ADMIN_TELEGRAM_ID sudah ada) → masuk sbg
`admin` → ganti sandi → kosongkan lagi. Belum ada satu akun pun di produksi.
Log deploy: bot admin `TelegramConflictError` — ada instance lain memegang token yang sama.

**YANG DIBANGUN SETELAH B3 (sesi 3-4 Sep 2026):**
- **Bilah navigasi 4 tab** (Beranda·Catat·Berjalan·Laporan) + layar **Berjalan**. Lencana
  menghitung yang menunggu ORANG saja, bukan yang menunggu waktu. Tiap baris menaut ke
  aksi yang MENUTUPnya: `/aksi?buka=<id>&nilai=<penanda>` — lembarnya terisi sendiri.
- **PEMISAHAN LOT, 3 tahap (arah B pilihan pemilik).** `drying_lots` = satu PROSES
  PENGERINGAN; apa-yang-digiling-bersama didaftar di `milling_process_sources` (migrasi
  0031). Menemukan kebocoran nyata: silo campuran hanya tergiling 10 dari 14 ton.
  `milling.sumber_batch()` jadi SATU penyelesai untuk HPP & analitik; biaya pengeringan
  dihitung PER BATCH. Aturan "silo harus kosong" dan kapasitas silo DICABUT.
- **Tumpukan gabah**: 2 (basah/kering), tanpa batas, tersirat dari kondisi batch — tanpa
  kolom baru. Status `ditumpuk` (kosakata sama dengan PK Gudang 2). Muncul di Berjalan
  sebagai tanda pembelian berlebih, bukan penyimpanan yang tenang.
- **Tiap dryer berjalan sendiri** (migrasi 0032 `purchase_batches.dryer_id`). Tujuan
  bernomor: `dryer:<id>`, `silo:<id>`; `peta_jenis` tak lagi menyebut SILO_A/SILO_B.
  Kapasitas dryer 30 ton + toleransi 3 ton → ditolak di atas 33 ton.
- **TELEGRAM DIHAPUS UNTUK OPERATOR**: bot gudang1+gudang2 (1.157 baris) dihapus, token
  dilepas dari `settings.bot_tokens`, initData operator ditolak 403. Bot admin TETAP hidup.
- **Tidak ada lagi jalur "manual tanpa timbang"** — gabah maupun PK, layar maupun chat.
- **Pengaturan** (`/pengaturan`): ganti nama sendiri, sandi, kelola pengguna, dan **alat**
  (tambah dryer/silo). Halaman **ubah akun** per orang (nama, username, peran, mode
  perangkat) + penjaga akun-tertinggi-terakhir.
- **Uji**: 141 uji satuan · `scripts/skenario_gabah.py` (10 skenario, DB bersih tiap
  skenario) · `scripts/simulasi_gabah.py` (12 babak, satu hari kerja). Keduanya butuh
  Postgres docker (port 55435/55434) dan MENOLAK berjalan di DB lain.

**TANGGA PERAN TERJAWAB 3 Sep: SUPER ADMIN / ADMIN / OPERATOR.** "Direksi" dikonsolidasi
jadi Super Admin dan kata itu dihapus dari seluruh layar. Kode sudah memakainya.
**TETAPI DATA `users.role` BELUM DIMIGRASI, dan ini TERKUNCI:** aplikasi KANTOR membaca
`users.role` yang SAMA dan memeriksanya sebagai `{"admin","staff"}`
(kantor/app/bots/common.py, kantor/app/kantor/bot.py). Mengubah nilainya jadi "superadmin"
membuat orangnya kehilangan akses KANTOR. Sampai kedua repo diselaraskan, produksi
menerima "admin" DAN "superadmin" sebagai tingkat tertinggi, dan "staff" lama tetap boleh
melihat angka uang (`bots.common.PERAN_UANG`).

**B3 SELESAI 2026-09-02 — ENAM LUBANG TUNTAS.** Cabang `feat/b3-lubang-fitur`
(4 commit: fbd8d54, 9fb03cf, b1daefb, 5d929e4). BELUM di-merge ke main, BELUM di-deploy.
84 uji lulus. Isinya:
- `app/web/aksi_umum.py` — penolong bersama (wajib/galat/kabar_chat/rp/kg), dipisah dari
  miniapp supaya modul aksi baru tak melingkar; miniapp memakai alias nama lama.
- `app/web/aksi_inventory.py` — kemasan, barang jadi, barang keluar (7 POST + 6 remote).
  KUNCI DESAIN: kombinasi kemasan ditawarkan sebagai SATU pilihan (kategori|material|ukuran),
  diturunkan dari `packaging.KEMASAN_VALID` bukan disalin — bot dulu menolak kombinasi
  mustahil SESUDAH orang mengetik.
- `app/web/aksi_undo.py` + `services/undo.pratinjau_terakhir()` — undo dgn PRATINJAU:
  yang ditawarkan adalah kalimat "gabah masuk · PB-... · 02/09 14:32 oleh Rusdi", dan itulah
  yang ditekan. Pratinjau & pembatalan pakai SATU kueri `_log_terakhir` (ada uji penjaga).
  Operator hanya lingkup "saya"; staff/admin bisa pilih lingkup, tiap lingkup tampil beserta
  tindakan terakhirnya.
- `app/web/laporan.py` + `templates/laporan.html` — 14 laporan teks yang sudah ada, dipilah
  uang/non-uang, hak diperiksa DUA kali (daftar + saat diminta). `ke_html()` escape DULU baru
  terjemahkan Markdown (kebalikannya = celah XSS lewat nama supplier).
- `app/web/pengguna.py` +`/pengguna/orang-baru` & `register_user(lewat_sandi=True)` — daftar
  orang baru TANPA Telegram ID. Status jadi "aktif" (bukan pending) krn pending membuatnya
  tak muncul di daftar "belum punya akun" sehingga akunnya tak pernah bisa dibuat.
- `aksi.js`: `optional` kini berlaku utk field remote; daftar kosong tak lagi mematikan aksi
  bila field-nya opsional. Template produksi kini bercap versi (`tampilan.VERSI`, sekarang "4").

**SEBAGIAN B2 SELESAI (commit 1c22d97):** `/aksi` — layar pencatatan di peramban. Kuncinya:
41 endpoint aksi kini menerima sesi webapp MAUPUN initData Telegram lewat `pengguna_aksi`
(app/web/deps.py); keduanya sengaja berdampingan sampai bot pabrik dimatikan. `static/aksi.js`
merender formulir dari spesifikasi server (`/miniapp/actions/menu`) — menambah aksi = menambah satu
spesifikasi Python, bukan layar baru. TERBUKTI ujung-ke-ujung: operator masuk lewat peramban,
catat gabah masuk manual, `input_by` = orang yang sedang masuk (tanpa Telegram sama sekali).

**UX yang diperbaiki setelah dipakai sendiri** (pemilik: "buat ui dan ux terbaik"): halaman masuk
mengingat nama yang pernah dipakai di perangkat itu (cookie berisi NAMA saja, bukan token) → pilih
nama, ketik sandi; nama tak hilang saat sandi salah; tombol "lihat" sandi; ganti sandi WAJIB tak
minta sandi lama (orangnya baru saja membuktikan diri, dan sandi yang diminta justru yang dibuang);
selesai → kembali ke beranda dgn kabar (hanya kunci pesan dikenal, teks bebas dari URL tak pernah
ditampilkan); usul nama pengguna dari nama depan (lewati inisial); sandi awal sbg blok besar sekali
baca; konfirmasi utk nonaktifkan/setel-ulang; daftar pilihan kosong dijelaskan SEBELUM tekan Simpan.

**B1 SELESAI, DIDEPLOY & TERVERIFIKASI LIVE (2026-09-02, commit bab72f7).** Produksi kini punya
pintu masuk sendiri: `/masuk`, `/ganti-sandi`, `/pengguna`, beranda di `/`. Terbukti live: `/` dan
`/pengguna` mengalihkan ke `/masuk` (303), halaman masuk terender, migrasi 0030 jalan di DB live.
Uji: 22 uji satuan (`tests/test_akun_webapp.py`) + `scripts/uji_webapp_b1.py` (28 pemeriksaan
ujung-ke-ujung di Postgres docker, semuanya lulus). Suite produksi 38 lulus.
Isinya: tabel `produksi_akun` (kredensial SAJA, tanpa kolom peran — peran dibaca dari `users` lewat
relasi); `app/web/security.py` (scrypt pustaka standar + cookie HMAC, menyalin pola
timbangan/security.py); `app/web/{auth,pengguna,tampilan,seed_akun}.py` + templates Jinja.
SECRET_KEY sudah dipasang di Railway. **SISA SATU LANGKAH MANUAL PEMILIK: set `ADMIN_SANDI_AWAL`
di service penggilingan-beras → deploy ulang → akun pertama dibuat utk user ber-ADMIN_TELEGRAM_ID
(username `admin`), wajib ganti sandi saat pertama masuk, lalu kosongkan lagi variabelnya.**

**JEBAKAN yang terjadi & diperbaiki:** rute FastAPI `async def beranda(request)` TANPA anotasi
`Request` → FastAPI menganggapnya parameter query → 422, bukan error yang jelas. Selalu anotasi.

**Rancangan Fase B selesai & diserahkan 2026-09-02.**
Cetak biru: https://claude.ai/code/artifact/f12f077e-8532-4fd5-b598-be909650a30f

**TEMUAN KUNCI yang mengubah bentuk seluruh rencana:** `app/web/miniapp.py` (1.564 baris) BUKAN
sekadar UI Telegram — ia sudah webapp lengkap: 19 GET + 23 POST, dan **menu aksinya digerakkan
server** (server mengirim spesifikasi field/tipe/pilihan/sumber-remote, klien generik merender).
Yang mengikatnya ke Telegram cuma `app/web/deps.py` (49 baris, initData) + `telegram_auth.py`.
Jadi Fase B = ganti pintu masuk + tambal 6 lubang fitur + buang 3.147 baris bot. BUKAN tulis ulang.

**PERAN (pemilik menyebut 2026-09-02: "identitas mungkin akan menjadi peran; sekarang ada super
admin, admin, staff, operator").** Kenyataan terukur: ada TIGA kosakata peran yang hidup sendiri —
`users.role` = admin/staff/operator (master, teks bebas tanpa constraint); timbangan_akun.role =
SUPERADMIN/ADMIN/PETUGAS; Kantor = RBAC penuh (peran × domain × grant: direksi, hr_manager,
legal_officer, staff_hr, staff_legal, pegawai). Rancangan: JANGAN leburkan — RBAC Kantor terlalu
halus untuk 4 tingkat. Pisahkan dua pertanyaan: "seberapa jauh boleh melangkah" → satu tangga
`users.role` (ditambah `superadmin` = 4 tingkat, dibawa sesi login, TANPA migrasi karena kolomnya
String bebas); "boleh apa di aplikasi ini" → tetap milik aplikasinya (produksi: lingkup gudang
G1/G2; Kantor: grant domain; timbangan: perannya sendiri). Tabel `akun` SENGAJA tanpa kolom peran
supaya peran tak tersalin di dua tempat lalu berbeda diam-diam.

**Enam keputusan rancangan:** (1) kredensial naik ke `hmu_core` sbg tabel bersama `akun`
(user_id UNIQUE + username + password_hash), identitas tetap di `users` — supaya satu sandi untuk
Timbangan & Produksi; mekanisme menyalin `timbangan/app/timbangan/security.py` (216 baris, scrypt
pustaka standar + cookie HMAC, tanpa dependensi baru). (2) API JSON & spesifikasi-aksi-dari-server
DIPERTAHANKAN: `/miniapp/*` → `/api/*`, tukar `require_miniapp_user` → `butuh_akun`; cangkang baru
ikut pola Timbangan (Jinja + static + PWA manifest/sw). (3) hak akses tetap ditentukan server.
(4) TULIS lewat formulir (608 baris NLP jalur-bot dihapus), TANYA boleh bahasa alami lewat agen yang
sudah ada — staff/admin saja, operator tidak. (5) notifikasi pakai tabel `notifications` yang SUDAH
ADA (tipe/target_role/prioritas/status) sbg pusat notifikasi in-app; eskalasi penting lewat bot
Kantor; Web Push belakangan. (6) enam lubang wajib ditambal sebelum bot dimatikan: kemasan, barang
jadi, barang keluar, laporan/analitik, kelola pengguna, tombol batal (semua service-nya sudah ada).

**Urutan: B1 login → B2 cangkang webapp → B3 enam lubang + notifikasi → B4 masa berdampingan 1–2
minggu → B5 matikan bot.** Bot BARU dimatikan di tahap terakhir; sampai itu webapp & bot hidup
berdampingan di atas service yang sama.

**EMPAT KEPUTUSAN MENUNGGU PEMILIK** (jangan mulai B1 sebelum #1–#3 dijawab):
1. ✅ TERJAWAB: LOKAL di repo produksi (`produksi_akun`), hmu_core tidak disentuh. Alasan:
   model akses belum diputuskan, dan tabel di lapisan bersama adalah tempat model akses mengeras
   diam-diam. Bisa dinaikkan ke core kelak dengan rename + pindah pemilik chain;
2. ✅ TERJAWAB (dan sempat berbalik): operator pakai **perangkat GUDANG** — alasan pemilik:
   kerahasiaan, data pabrik tak boleh menetap di HP pribadi lalu ikut keluar bersama orangnya.
   Admin & petinggi pakai perangkat masing-masing. Diterapkan sbg `mode_perangkat` per akun
   ('bersama' 45 menit diperpanjang tiap permintaan = mati saat menganggur; 'pribadi' 30 hari),
   bawaannya dari peran lewat `mode_bawaan()`;
3. arti `superadmin` vs `admin`. Usulan saya (pola timbangan): superadmin = pemilik sistem — kelola
   akun & sandi, ubah tarif biaya, koreksi data terkunci; admin = Direksi — semua aksi operasional
   termasuk data uang, tapi tak menyentuh akun orang lain / parameter biaya. Menentukan bentuk
   halaman kelola pengguna di B1;
4. kotak tanya bahasa alami: dibuat sekarang atau tunda ke setelah B5 (saran saya: tunda).

**#3 MASIH TERBUKA setelah B3.** Layar kelola pengguna dibangun dgn tangga yang ADA
(operator/staff/admin = `user_admin._ROLES`), TIDAK mengarang tingkat `superadmin`. Ada uji
yang memaksa peran di layar == `_ROLES`; menambah superadmin berarti mengubah keduanya.

**SISA FASE B setelah B3:** notifikasi in-app (pakai tabel `notifications` yg sudah ada) ·
PWA produksi (manifest+sw, tiru timbangan) · B4 masa berdampingan 1-2 minggu · B5 matikan
3 bot pabrik (buang ~3.147 baris + jalur initData di `deps.py`).

Terkait: [[pisah-kantor-produksi]], [[timbangan-module]], [[workspace-layout]],
[[penggilingan-beras-project]].


**PWA & KECEPATAN — SELESAI 2026-09-04 (VERSI aset 20).**

*Perpindahan halaman.* Diukur, bukan ditebak: render server ~20 ms, tetapi byte pertama
272 ms — layanan di region `sfo` sementara pemakainya di Indonesia. Jaraknya yang lambat,
bukan aplikasinya. Pemilik memilih pertukarannya: "data agak lambat tidak apa-apa, paling
tidak perpindahan halaman responsif." Jawabannya `app/web/static/pindah.js` — halaman
bertab dipra-ambil saat menganggur, disimpan DI MEMORI (bukan cakram/service worker: isinya
angka perusahaan & menempel pada sesi), ditampilkan seketika, diperbarui diam-diam.
Hasil: 0–8 ms per pindah tab. Penyegaran ditahan selama ada lembar terbuka; simpanan
dikosongkan lalu DIPANASKAN ULANG sesudah tiap POST. Pendengar tingkat dokumen WAJIB lewat
`PINDAH.pasang` — kalau tidak, ia menumpuk sekali tiap perpindahan.
**Pemindahan region ke Singapura masih terbuka & itu keputusan pemilik** — DB harus ikut
pindah, dan 3 layanan berbagi satu DB.

*Pita kosong di bawah bilah navigasi — TUJUH putaran, dan sebabnya di luar CSS.*
Urutan yang meleset: `bottom:0` → `100dvh` → `inset:0` → meta `black` (dibatalkan) →
manifest. Semuanya mencari di dalam halaman. **Kerangkanya tak pernah salah** — terukur
atas 0, tinggi 793, sisa di bawah 0; ia mengisi jendelanya persis.
**Sebabnya `apple-mobile-web-app-status-bar-style: black-translucent`**: jendelanya dibuat
setinggi layar dikurangi bilah status TAPI diletakkan mulai dari paling atas, jadi 59 pt
(= `env(safe-area-inset-top)`) tersisa di bawah — di LUAR jendela, tak terjangkau CSS apa
pun. Terukur: jendela 793, layar 852, inset atas 59. **Perbaikannya `content="black"`.**
Manifest TIDAK memperbaiki pita ini (jendela tetap 793) — tetapi tetap dipertahankan &
benar untuk hal lain: ikon layar utama (sebelumnya iOS memakai potret halaman) + display
standalone. **Jebakan yang membuang 2 putaran: Pos Timbang memakai `black-translucent` yang
sama dan "tampak sampai bawah" — karena ia BERLATAR TERANG, 59 pt matinya sewarna
halamannya. Perbandingan antar-aplikasi menyesatkan kalau warnanya berbeda.** Jebakan
kedua: `black` sempat dicoba di v17 lalu dibatalkan, dan pemasangan ulang pemilik terjadi
SETELAH pembatalan — jadi ia tak pernah diuji dengan adil. **iOS mengunci meta ini saat
PEMASANGAN: tiap perubahannya menuntut hapus & pasang ulang ikon.** Jaring pengaman
permanen: `html { background: var(--panel) }` mewarnai kanvas di luar jendela, jadi
kekurangan serupa terbaca sebagai bilah memanjang, bukan lubang.

*Cara mendiagnosis yang akhirnya berhasil — pakai ini kalau terulang.* Bukan halaman ukur
terpisah (ia melapor 852 sementara aplikasi 793, dan bedanya menyesatkan), melainkan skrip
yang MEMATIKAN tiap tersangka SAAT BERJALAN lalu membaca ulang `innerHeight` — semua
tersangka terjawab dalam SATU tangkapan layar, bukan satu deploy per tebakan.

*Pelajaran alat.* Masalah tampilan iOS TIDAK bisa didiagnosis dari peramban di Mac: ia tak
punya area aman, takik, maupun indikator beranda, dan selalu menjawab "sisa bawah 0 px".
Halaman ukur sementara yang dibuka DARI DALAM aplikasi terpasang adalah yang memberi angka
penentu. Dua jebakan saat membuatnya: jangan pasang `butuh_akun` (tautan dibuka di peramban
tanpa sesi → yang tampil halaman masuk), dan jangan ukur `env()` lewat
`getComputedStyle().height` pada elemen tanpa lebar (Safari menjawab "0px" — angka palsu).
