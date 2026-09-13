# Pos Produksi — PT Hadi Mulya Utama

Sistem pencatatan penggilingan beras. Dipakai operator sambil berdiri di
gudang, memegang telepon dengan satu tangan, kadang kena matahari. Itu bukan
warna latar cerita — ia yang menentukan hampir semua keputusan rancangan di
sini.

> `README.md` sudah USANG: ia masih menyebut tiga bot Telegram. Bot produksi
> dibubarkan 8 September 2026; pencatatan seluruhnya lewat webapp ini. Yang
> tersisa satu bot, milik Kantor, untuk Direksi & pengawas — baca saja.

## Tempat kerja

Empat repo BERSEBELAHAN di satu folder induk (`Hadi Mulya Systems/`):
`produksi/` (ini), `kantor/`, `timbangan/`, `website/`.

**Basis datanya SATU** — Postgres yang sama dipakai produksi, timbangan, dan
Kantor. Menghapus baris "milik sendiri" bisa merobohkan layanan sebelah.
Sebelum menghapus massal, periksa siapa lagi yang membaca tabelnya.

## Bahasa

Kode, komentar, nama fungsi, dan teks layar berbahasa **Indonesia**. Bukan
selera: yang membaca layarnya orang Indonesia, dan istilah yang diterjemahkan
bolak-balik akan berbeda arti di dua tempat.

Komentarnya panjang dan menjelaskan **kenapa**, bukan apa — sering menyebut
kesalahan yang pernah terjadi dan kenapa jalan lain ditolak. Itu disengaja.
Ikuti gayanya: komentar yang cuma mengulang isi baris di bawahnya lebih baik
tak ada.

## Bentuk

FastAPI · SQLAlchemy 2 async (asyncpg) · Alembic · Jinja2 dirender server ·
CSS & JS biasa, **tanpa langkah build**. Python 3.11.

- `app/web/` — layar & rute webapp. `app/web/miniapp.py` menyajikan katalog
  AKSI per peran; kliennya `static/aksi.js` yang generik.
- `app/services/` — logika lintas gudang. `berjalan.py` menyusun isi layar
  antrean/berjalan; `stok.py` isi layar Stok.
- `app/penggilingan/gudang1/` (selepan: gabah → PK) dan `gudang2/`
  (penyosohan: PK → beras putih).
- `app/peran.py` — aturan peran. `app/web/layar.py` — VIEW.

**Perpindahan halaman instan** (`static/pindah.js`): isi `.bingkai` ditukar
dan skrip di dalamnya dijalankan ulang. Konsekuensinya: pendengar yang
dipasang pada `document` menumpuk tiap perpindahan — pakai `PINDAH.pasang`.

**CSS, JS, ikon, `base.html`, dan `_benda.html` BUKAN milik repo ini** sejak
13 September 2026 (Tahap 1 rancang ulang, temuan QA X-22): sumbernya repo
`tampilan/` (paket `hmu_tampilan`), di-vendor ke `hmu_tampilan/` di sini oleh
`tampilan/scripts/sinkron.py`. Jangan sunting folder vendored itu — ubah di
repo tampilan, naikkan `VERSI` di sana, sinkronkan. Uji
`tests/test_tampilan_paket.py` menolak salinan dan vendored yang basi.
`app/web/tampilan.py` hanya mengekspor ulang `VERSI` dari paket.

## Peran & empat view

Tangga: `operator` · `admin` (disebut **Direksi** di layar) · `superadmin`.
`staff` peran LAMA yang masih sah dibaca.

**Jangan pernah menyebut peran satu per satu** (`role == "admin"`,
`in ("admin","staff")`, `{"admin","staff"}`). Pakai `PERAN_STAF_KEATAS` /
`PERAN_ADMIN_KEATAS` dari `app/peran.py`. Peran baru yang ditambahkan di
puncak sudah SEMBILAN KALI tertinggal di gerbang yang menyebut nama — sekali
di antaranya mematikan bot Kantor sepenuhnya. Ada uji yang menjaganya.

Empat VIEW, ditetapkan sekali per permintaan di `akun_opsional` dan dibaca
`app/web/layar.py`: `super` · `admin` · `selepan` (operator Gudang 1) ·
`polesan` (operator Gudang 2). Layar TIDAK menghitung sendiri "ini operator
gudang mana".

Mengelola orang, akun, dan alat: **Super Admin saja**, dengan jaring pengaman
— selama tak ada satu pun Super Admin aktif, Direksi diterima, supaya pabrik
tak pernah terkunci dari dalam. Setelan KERJA (target kadar air, sebab
berhenti, sakelar mutu) tetap milik Direksi.

## Kode barang

Otoritasnya `app/services/codegen.py`, bukan ingatan:
`GB` pembelian gabah · `PGR` pengeringan · `LOT` giling · `TRF` transfer PK ·
`PKB` beli PK luar · `POL` penyosohan · `PTS` pindah tumpukan · `REJ` PK
ditolak · `OUT` barang keluar · `PKP` beli kemasan.

Awalan yang salah pernah membuat lapisan AI mengarahkan perintah ke proses
yang keliru. Kalau menyentuh teks yang memuat awalan, periksa konteksnya satu
per satu — jangan sapu dengan `sed` global.

## Uji

```
.venv/bin/python -m pytest -q
```

### Uji ber-Postgres (`tests/pg/`)

Dilewati secara bawaan. Satu kelas kesalahan hanya muncul di basis data
sungguhan — BALAPAN: dua operator menekan simpan pada detik yang sama, atau
satu pembatalan menggeser hitungan. SQLite tak menirukannya, dan sampai 11
September 2026 suite ini tak punya satu pun uji ber-Postgres. Akibatnya
tabrakan kode harian (P-K-01) berjalan berbulan-bulan tanpa terlihat.

```
createdb uji_produksi
UJI_PG_URL=postgresql+asyncpg://postgres:pw@127.0.0.1:5432/uji_produksi \
    .venv/bin/python -m pytest -q tests/pg
```

Skemanya dibangun lewat `alembic upgrade head`, bukan dari metadata —
migrasinya sendiri ikut diuji, dan membangun dari metadata akan melewatkannya
lalu lulus di laptop dan gagal di Railway.

Alamatnya BERPAGAR dan gagal keras bila melanggar: host wajib loopback, nama
basis data wajib berawalan `uji_`. Uji ini membangun dan menjatuhkan skema;
satu salah ketik pada alamat yang tak berpagar bisa mengenai basis data yang
sedang dipakai orang.

Ujinya banyak yang membaca SUMBER dan TEMPLAT, bukan cuma menjalankan fungsi
— itu disengaja, karena yang sering rusak adalah aturan yang tak punya tempat
lain untuk dijaga. Kalau sebuah uji gagal karena aturannya memang berubah,
perbaiki ujinya berikut alasannya; jangan longgarkan polanya diam-diam.

**Uji penjaga yang polanya kurang lengkap lebih buruk daripada tak ada uji.**
Saat menyapu pemakaian harfiah, cari dengan regex yang menerima semua bentuk
sintaks, lalu buktikan penjaganya benar-benar gagal pada kasus lama.

## Kirim

| Layanan | Cara |
|---|---|
| `penggilingan-beras` (produksi) | `git push origin main` — terbit sendiri |
| `pos-produksi-uji` (staging) | `git push origin main:uji` |
| `kantor` | **`railway up --service kantor`** dari repo `kantor/` — TIDAK tertaut GitHub |
| `timbangan` | repo `timbangan/` |

Kirim ke uji dulu, tunggu SUCCESS, baru produksi.

## Rahasia Railway — aturan keras

Sebuah kunci akun layanan Google pernah BOCOR ke transkrip lewat
`railway variables --kv | cut -d= -f1`.

- **JANGAN** menjalankan perintah yang membaca NILAI variabel.
- **JANGAN** memakai `--kv`, dalam bentuk apa pun.
- **JANGAN** memakai `railway config pull --include-variables`.
- Melihat NAMA variabel dengan aman: `railway variable list --service <svc>
  --json`, disalurkan ke pengurai JSON yang mencetak kuncinya saja.
- Menaruh rahasia: lewat `--stdin` atau berkas. Jangan pernah dicetak.

Masuk ke kontainer: `railway ssh --service <svc> -- <perintah>`. Itu
satu-satunya jalan menjangkau basis data yang tak terbuka ke publik — dan
satu-satunya kebenaran soal versi mana yang benar-benar berjalan pada layanan
yang tak tertaut git.

## Catatan lebih panjang

`docs/ingatan/` menyimpan catatan proyek yang tak muat di sini: riwayat
keputusan, jebakan yang pernah memakan waktu, dan keadaan tiap bagian.
Mulailah dari `docs/ingatan/MEMORY.md`.
