# Pos Produksi — PT Hadi Mulya Utama

Sistem pencatatan penggilingan beras. Dipakai operator sambil berdiri di
gudang, memegang telepon dengan satu tangan, kadang kena matahari. Itu bukan
warna latar cerita — ia yang menentukan hampir semua keputusan rancangan di
sini.

> `README.md` sudah USANG: ia masih menyebut tiga bot Telegram. Bot produksi
> dibubarkan 8 September 2026; pencatatan seluruhnya lewat webapp ini. Yang
> tersisa satu bot, milik Kantor, untuk Direksi & pengawas — baca saja.

## Tempat kerja

Repo BERSEBELAHAN di satu folder induk (`Hadi Mulya Systems/`): `produksi/`
(ini), `core/`, `tampilan/`, `kantor/`, `timbangan/`, `website/`. App Gudang 2
dan app Meja pernah ada di sini; keduanya dihapus 24 September 2026.

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

- `app/web/` — layar & rute webapp. `app/web/api.py` menyajikan katalog
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

## Identitas, peran & empat view

**Identitas adalah paket bersama `hmu_identitas`** (repo `core/`, di-vendor
ke `hmu_identitas/` di sini oleh `core/scripts/sinkron.py`; Tahap 2 rancang
ulang, 13 Sep 2026). Sandi, token sesi, model akun (`Akun` = tabel
`produksi_akun`, nama tabel tak diganti), "boleh masuk?" (`masuk.akun_aktif`,
`masuk.periksa_kredensial`), satu saklar nonaktif (`masuk.nonaktifkan`), dan
pintu per aplikasi (`pintu.boleh_masuk`) ada di sana — dipakai timbangan,
Meja, Gudang 2, dan Kantor juga. Jangan sunting folder vendored; ubah di
`core/`, sinkronkan. `app/web/security.py` tinggal kunci, cookie, view.

Tangga: `operator` · `admin` · `superadmin`. `staff`/`staf` nama LAMA yang
masih sah dibaca. Pintu per aplikasi (keputusan pemilik): operator → app
operator, admin → Meja, timbangan → operator & admin, superadmin → semua;
Pos Produksi masih menerima admin sampai Meja dipakai sungguhan.
**Operator tidak terikat satu gudang** (pemilik 13 Sep: saling menggantikan):
gudang utama = layar pertama; berpindah lewat "Kerja di gudang" di Pengaturan
(`/lihat-sebagai` dengan `operator:g1|g2`, ditetapkan per permintaan di
`akun_opsional`). Aplikasi Gudang 2 mengirim `X-Meja-Lihat: operator:g2`
di tiap panggilan. `_is_g1_operator`/`_is_g2_operator` memeriksa gudang yang
SEDANG dikerjakan, bukan gudang utama.

**Jangan pernah menyebut peran harfiah** (`role == "admin"`,
`in ("admin","staff")`, `u.role = "admin"`). Pakai `hmu_identitas.peran`
(`admin_keatas`, `staf_keatas`, `operator_saja`, `PERAN_*`, `TINGKAT`,
`terlalu_tinggi`). Uji AST `tests/test_identitas_paket.py` menolak seluruh
`app/`. Peran baru di puncak sudah SEMBILAN KALI tertinggal di gerbang yang
menyebut nama — sekali di antaranya mematikan bot Kantor sepenuhnya.

Empat VIEW, ditetapkan sekali per permintaan di `akun_opsional` dan dibaca
`app/web/layar.py`: `super` · `admin` · `selepan` (operator Gudang 1) ·
`polesan` (operator Gudang 2). Layar TIDAK menghitung sendiri "ini operator
gudang mana".

Mengelola orang, akun, dan alat: **Super Admin saja**, dengan jaring pengaman
— selama tak ada satu pun Super Admin aktif, Direksi diterima, supaya pabrik
tak pernah terkunci dari dalam. Setelan KERJA (target kadar air, sebab
berhenti, sakelar mutu) tetap milik Direksi.

## Peristiwa — tulang punggung baru (Tahap 3, sejak 13 September 2026)

`peristiwa` = apa yang terjadi, TAMBAH-SAJA (trigger Postgres menolak UPDATE
dan DELETE). `proyeksi_*` = turunan dari peristiwa, ditulis di transaksi yang
sama, bisa dibangun ulang dari nol: `python -m scripts.bangun_ulang_proyeksi`.
Pembatalan = peristiwa LAWAN (`membatalkan_id`), bukan penghapusan.
**Cermin bertanda, bukan dihapus** (sejak migrasi 0052): baris cermin di
`purchase_batches`, `pk_purchase_batches`, `pk_gudang2_intakes`,
`pk_tumpukan_to_silo` yang dibatalkan mendapat `dibatalkan_pada`, dan SEMUA
pembaca ORM menyaringnya otomatis lewat saringan sesi di
`app/models/cermin.py` (`internal_transfers` memakai `status`). SQL mentah
(`text(...)`) harus menyaring sendiri `dibatalkan_pada IS NULL` — beri
komentar "cermin bertanda". Jalur yang memang perlu melihat baris batal
memakai `execution_options(termasuk_dibatalkan=True)`. Constraint unik tiket
timbang kini indeks parsial `uq_<tabel>_timbangan_hidup`.

Aksi yang sudah di jalur ini: **Gabah masuk dari tiket timbang**
(`purchase.create_purchase_batch_dari_timbang`, undo `_undo_purchase`) dan
**PK luar masuk dari tiket timbang** (`gudang2.service.
create_pk_purchase_dari_timbang`, undo `_undo_pk_purchase`, proyeksi
`proyeksi_pk_luar_masuk`, migrasi 0048), dan **PK masuk Gudang 2** ke
silo/tumpukan (`gudang2.service._add_intake` — satu titik tulis untuk PK
luar DAN transfer G1; undo `_undo_pk_intake` DITOLAK bila silonya sudah
dipoles sesudah PK masuk atau tumpukannya sudah dipindah — P-K-10; proyeksi
`proyeksi_pk_masuk_g2`, migrasi 0049), dan **Pemindahan PK G1 → G2**
(`services.transfer.create_internal_transfer`: dua peristiwa satu transaksi,
`pk_dipindah_g1g2` lalu `pk_masuk_g2`; undo `_undo_transfer` membatalkan
keduanya lewat penjaga hilir; cermin `internal_transfers` TIDAK dihapus,
statusnya `dibatalkan`; proyeksi `proyeksi_transfer_pk`, migrasi 0050).
Pemasukan yang lahir dari transfer tak bisa dibatalkan sendiri — dialihkan
ke pembatalan transfernya. Kelima: **Pindah tumpukan ke silo**
(`gudang2.service._catat_pindah` dipakai `pindah_tumpukan_ke_silo` (baris
tumpukan dikunci FOR UPDATE) dan `pindah_tumpukan`; undo baru
`_undo_pindah_tumpukan` dengan penjaga silo yang sama; proyeksi
`proyeksi_pindah_tumpukan_silo`, migrasi 0051). Urutan satu transaksi: kunci tiket → nomor atomik →
`services.peristiwa.catat` (kunci kiriman idempoten) → proyeksi → CERMIN
`purchase_batches` (layar lama membacanya; saat dibatalkan ditandai, tidak dihapus) → jejak & notifikasi →
commit. Aksi lain masih jalur lama; memindahkannya satu per satu, dengan
persetujuan pemilik, dan tiap aksi wajib punya uji Postgres dua sesi
(`tests/pg/test_peristiwa.py` contohnya: r06, r13). Muatan JSON hanya lewat
`peristiwa.bersih()`.

## Satu lot giling, beberapa silo (sejak 24 September 2026)

Keputusan pemilik: menggiling dari beberapa silo sekaligus "sering", dan
"hasilnya 1 lot" — satu rendemen dan satu HPP atas seluruh bahannya.

`MillingProcess.silo_id`, `silo_storage_id`, `drying_lot_id`,
`purchase_batch_id` adalah **PENINGGALAN**: masing-masing menyebut SALAH SATU
sumber, dan tak boleh lagi menentukan perilaku apa pun. Yang berwenang
`milling_process_sources` — satu baris per sumber. Dua jawaban bersama:

  · `silo.giling_berjalan_untuk_silo(db, silo_id)` → "silo ini sedang
    digiling?" (dipakai kartu antrean, borang, dan gabah yang datang saat
    giling berjalan — ketiganya);
  · `silo.silo_ids_proses(db, proc)` → himpunan silo sebuah proses.

Keduanya punya kaki kedua lewat `silo_id` untuk proses LAMA yang lahir sebelum
tabel sumber ada. Jangan tambah tabel anak seperti `polishing_silo_usage`:
Gudang 2 memerlukannya karena punya SISA PER SILO, Gudang 1 tidak — `selesai`
mengosongkan seluruh sumbernya sekaligus.

"Satu giling berjalan per silo" dijaga `silo_storage.milling_process_id`
(migrasi 0056), direbut dengan `UPDATE … WHERE milling_process_id IS NULL` —
bukan indeks unik (syaratnya ada di baris tabel lain) dan bukan pemeriksaan di
depan (dua penekan bersamaan sama-sama lolos).

## Tempat PK di Gudang 2 = rujukan silo (sejak 24 September 2026)

`silo_a`/`silo_b` DIPENSIUNKAN sebagai kosakata. Yang disimpan kini JENIS
tempatnya — `silo` atau `ditumpuk` — dan silo MANA jadi `silo_id`:
`pk_gudang2_intakes`, `internal_transfers`, serta dua tabel proyeksinya
(migrasi 0057 menambahkan kolomnya ke dua tabel yang belum punya, dan
mengisinya dari kata lama).

Sebabnya: kosakata yang memuat nama silo tak bisa tumbuh. Silo ketiga ada di
master, tampil di borang, dan tak bisa menerima satu kilogram pun — temuan QA.

Aturannya sekarang:

  · nama silo TIDAK pernah diketik di kode. Tujuan dinormalisasi
    `gudang2.service._tujuan_and_silo` (menerima "C", "Silo C", dan bentuk lama
    `silo_a`), labelnya `label_tujuan` — keduanya membaca master;
  · stok & HPP silo disaring dengan `silo_id` SAJA. Menambah syarat atas kata
    tujuannya membuang baris silo baru DIAM-DIAM: silonya berisi, stoknya
    terbaca 0, lalu ia hilang dari borang tanpa satu pun galat;
  · kata lama tetap SAH di baris lama dan di muatan peristiwa (tambah-saja),
    dan tetap diterima saat membaca masukan — halaman di ponsel berumur
    panjang. Yang berhenti cuma MENULISNYA.

## Jasa (toll milling) — satu-satunya batasannya KEPEMILIKAN (sejak 1 Okt 2026)

Barang pelanggan yang digiling di sini **tidak dibeli**. `jasa.id` menjawab
"milik siapa", dan **`jasa_id` NULL = milik pabrik** — seluruh perilaku sebelum
migrasi 0064 tak bergeser satu baris pun, tanpa backfill.

`purchase_batches.supplier_id` kini BOLEH NULL, dengan
`CHECK ck_purchase_batches_beli_atau_jasa`: tepat satu dari `supplier_id` /
`jasa_id` terisi — dibeli, ATAU dititipkan. ⚠ Jangan pernah mengakalinya dengan
memasukkan pelanggan ke `suppliers`: pemasok palsu ikut ke skor pemasok, laporan
pembelian, dan HPP.

**SEBELAS tabel** membawa `jasa_id` — enam dari migrasi 0064 (`purchase_batches`
· `drying_lots` · `silo_storage` · `milling_process` · `internal_transfers` ·
`pk_gudang2_intakes`) dan lima dari **0065** (`pk_purchase_batches` ·
`polishing_process` · `finished_goods_stock` · `byproduct_stock` ·
`outgoing_records`). Dengan 0065, jasa hidup untuk **KETIGA komoditasnya** —
gabah basah, gabah kering, beras PK — keputusan pemilik nomor 1.

`pk_tumpukan_to_silo` SENGAJA tidak ikut: pemindahan tumpukan→silo tak
memperkenalkan pemilik baru, dan pemiliknya sudah ada di intake asalnya
(`jasa.pemilik_silo_g2`). Kolom kedua yang berarti hal sama adalah kolom yang
suatu hari berselisih dengan yang pertama.

**Gabah basah JASA wajib ke pengering** (`tumpukan.tujuan_sah`,
`masuk_tumpukan` menolak): basah yang menumpuk akan rusak, dan rusaknya jadi
perselisihan dengan yang menitipkannya. Gabah basah PABRIK tetap boleh
menumpuk — yang dibatasi hanya barang orang lain.

⚠⚠ **BEKATUL: SATU KOLOM MEMIKUL DUA ARTI, DAN KEDUANYA HARUS HIDUP.**
Keputusan pemilik 12: bekatul BERALIH milik ke pabrik, tetapi pemilik barang
tetap berhak tahu hasil bekatul dari tiap prosesnya.

    MILIK = pabrik         → `byproduct_stock.jasa_id` NULL, dan itu BENAR
    ASAL  = JAS-2610-012   → `source_id` → `polishing_process.jasa_id`

Keputusannya ditaruh SEKALI di hulu (`jasa.pemilik_hasil()`), dan itu yang
membuat saringan `WHERE jasa_id IS NULL` di hilir tak butuh satu pun cabang
khusus: bekatul jasa memang HARUS muncul di perintah penjualan biasa. ⚠ Naluri
pertama saat menulis saringan adalah "sembunyikan segala yang berbau jasa" —
bekatul justru pengecualiannya, dan ia lolos sendiri.

⚠ `packaging.py` juga SENGAJA tak disaring: karung jasa memang dari stok
kemasan PABRIK (keputusan pemilik), jadi karungnya sungguh terpakai.

`app/services/jasa.py` memegang aturannya:

  · `pastikan_satu_jasa()` — bukan larangan mencampur, **larangan mencampur
    PEMILIK**. Keputusan pemilik: *"yang tidak memungkinkan adalah menggabungkan
    barang jika kepemilikan berbeda. itu saja batasannya."* Barang sepemilik
    boleh satu silo, dua silo, digiling bersama — sebebas barang pabrik. Dan
    pencabutan larangan campur untuk gabah PABRIK (migrasi 0031) TETAP berlaku;
    jangan dipasang ulang "sekalian".
  · pembandingnya **`jasa_id`, bukan `pelanggan_id`**: dua pesanan satu
    pelanggan tetap terpisah, bobot kembalinya berbeda. ⚠ KARUNG
    (`packaging_purchases`/`packaging_losses`, sejak migrasi 0075)
    PENGECUALIANNYA — bukan kelalaian, melainkan keputusan pemilik 7
    Oktober 2026: karung bukan barang yang "dikembalikan" per pesanan,
    jadi pemiliknya `pelanggan_id` langsung, tanpa `Jasa` sama sekali.
    Lihat catatan panjang di `packaging.pindah_kepemilikan_karung`.
  · DITOLAK, bukan diperingatkan — dan **berkunci basis data** (`kunci_silo`,
    `kunci_dryer`): dua operator bisa menuang ke silo yang sama pada detik yang
    sama.

**Setiap pembaca stok PABRIK menyaring `jasa_id IS NULL`.** Tanpa itu Stok
menghitung barang pelanggan sebagai persediaan pabrik, lalu pabrik menjualnya —
dan itu tak melempar satu pun galat. Yang sudah disaring: `stok_pk_g1`,
`dashboard._stok_pk`, `tumpukan.jumlah_kg`, `beranda.angka_gudang`,
`gudang2.hitung_stok_silo`/`hitung_stok_tumpukan`, seluruh laporan pembelian
(`report.py`, `analytics.py`), dan daftar barang yang bisa keluar
(`aksi_inventory`) berikut penjaganya di `barang_keluar.tersedia`.

⚠⚠ **TETAPI MENYARING BUKAN MENYEMBUNYIKAN — ATURANNYA PUNYA DUA SISI.**
Laporan pemilik 2 Oktober 2026: *"pk yang selesai digiling tidak terlihat di
stock oleh admin dan operator gudang 2."* Bukan masalah izin: `/stok`
mendaftarnya, dan rantai permintaan→setujui→kirim menerimanya utuh. Yang rusak
ANGKA KEPALANYA — Beranda, baris gudang, dan papan Direksi menyebut "PK 0 kg"
sementara tujuh ton barang pelanggan berdiri di lantai, karena ketiganya
disaring jadi milik-pabrik **tanpa menyebut titipannya di sebelahnya**. Operator
lalu menyimpulkan tak ada apa-apa untuk dipindahkan.

    jangan pernah MENGHITUNG barang pelanggan sebagai milik pabrik
    jangan pernah MENGHILANGKANNYA dari layar

Saringan tanpa penyebutan sama berbahayanya dengan penjumlahan: yang pertama
membuat pabrik menjual barang orang lain, yang kedua membuat pabrik
membiarkannya menunggu di lantai sambil mengira gudangnya kosong. Pola
penyebutannya SATU: angka pabrik apa adanya, titipannya di sebelahnya dengan
kata **"titipan"** — `angka_gudang` → `g1/g2.jasa_pk`, `_stok_pk` →
`jasa_total`/`jasa_proses` (berikut kode `JAS-` supaya bisa ditindaklanjuti),
`gabah_hari_ini` → `jasa_kg`/`jasa_batch`.

Dan kartunya **menggambar** pemiliknya: `LotPk.pemilik` & `TempatPk.pemilik`
sempat dihitung lalu tak pernah disebut templatnya, jadi silo penuh barang
pelanggan tampak persis seperti silo pabrik. Markup-nya di
`hmu_tampilan/templates/stok.html` (repo `tampilan`) — penjaganya MERENDER
layarnya lewat HTTP, sebab penjaga versi hitung-teks lulus saat markup-nya
dimatikan dengan `{% if false %}`.

⚠ `hitung_stok_silo` menerima **tiga** nilai `pemilik` ("semua"/"pabrik"/
"jasa"), dan saringannya wajib menempel pada KETIGA bagian hitungannya: masuk
langsung, masuk lewat tumpukan, dan **`terpakai` penyosohan**. Yang ketiga
sempat tak disaring sama sekali — satu sosoh barang pelanggan lalu mengurangi
stok PABRIK silo itu sampai −1.000 kg, tanpa satu pun galat. Bentuk yang
menjaganya: `pabrik + jasa == semua` **sesudah ada sosoh berjalan** — tanpa
sosohnya invarian itu lulus dengan sendirinya.

⚠ Picker `/actions/pk-g1-tersedia` (permintaan Gudang 2) adalah **kebalikan**
dari dua picker PENJUALAN (`barang-bisa-keluar`, `pk-siap-keluar`): ia
MENAWARKAN lot jasa, sebab menyosoh barang pelanggan adalah pekerjaan yang
dipesan — yang dilarang menjualnya, bukan memindahkannya. Labelnya menyebut
`TITIPAN <pemilik>`.

Pesanan lahir di **app produksi** saat operator menerima tiketnya
(`purchase.pesanan_jasa_dari_tiket`), bukan di Pos Timbang: tiket bisa
dibatalkan, dan tiket batal yang sudah melahirkan pesanan meninggalkan pesanan
yatim. `timbangan_transaksi.jasa_id` adalah penunjuk ke pesanan BERJALAN —
itulah yang membuat dua truk jadi satu pesanan.

**Sisa & "SELESAI"** — `jasa.sisa_jasa()` adalah SATU sumber, dipakai kartu
maupun pemeriksaan penutupan. ⚠ Ia mengembalikan RINCIAN PER FASE dan tak pernah
satu angka: gabah yang sudah jadi PK tak lagi ada sebagai gabah, jadi
menjumlahkannya menghitung beras yang sama dua-tiga kali — dan angka itu dipakai
memutuskan berapa yang diserahkan. Aturannya satu kalimat:

    SELESAI = pernah ada barang masuk DAN tak ada lagi barang ber-`jasa_id` ini.

Syarat pertama bukan hiasan: pesanan yang baru lahir juga bersisa NOL, dan tanpa
`pernah_ada_barang()` ia terbaca selesai pada detik ia dibuat.

**Pengambilan** menumpang rantai barang keluar apa adanya (perintah · muat ·
verifikasi, satu truk satu perintah) — "boleh ambil bertahap" karena itu tak
butuh perubahan apa pun di sana. Yang ditambahkan: daftar barang yang
tersaring pemilik, dan `hitung_stok_finished_goods(..., jasa_id=)` — satu
rumus, dua pertanyaan, bawaannya PABRIK.

⚠⚠ **SATU TRUK BOLEH MENGGABUNG BEBERAPA PESANAN SATU PELANGGAN** (migrasi
0080, koreksi lapangan 12 Oktober 2026: *"pak pras punya pk di gudang 1 dan
gudang 2... sekali kiriman saya mau kirim semuanya"* — dua pesanan yang tak
pernah bertemu fisik jadi tak tergabung otomatis lewat `pastikan_satu_
pemilik`). Kepemilikan pindah ke `outgoing_items.jasa_id` (PER BARIS) —
`outgoing_records.jasa_id` sejak itu NULL kalau transaksinya menggabung lebih
dari satu pesanan, satu nilai tak lagi cukup. `pelanggan_id` TETAP satu nilai
selalu (pagar yang tetap keras: barang dua PELANGGAN tak boleh naik satu
truk, cuma pemisahnya kini pelanggan — bukan lagi nomor pesanan).
`jasa.sisa_jasa()` membaca kolom baris ini, bukan lagi kolom perintah.
Medan "Pesanan" di borang "Pengambilan barang jasa" DIHAPUS — picker
"Pelanggan" (`/actions/pelanggan-ada-barang-jasa`) langsung diikuti picker
"Barang yang diambil" (`/actions/barang-jasa?induk=<pelanggan>`), yang
menggabung SELURUH pesanan berjalan pelanggan itu; tiap nilainya membawa
akhiran `@<jasa_id>` asalnya sendiri, dibongkar `aksi_inventory._satu_baris`.

⚠ `barang_keluar.baris_dari_item()` wajib dipakai untuk menyusun ulang baris
perintah — SELALU membaca `jasa_id` dari `OutgoingItem` sumbernya sendiri
(sejak migrasi 0080; dulu dari `jasa_id` PERINTAHNYA, parameter eksternal
yang sudah dicabut dari tanda tangannya), dan tiga tempat pernah
melewatkannya — `tersedia()` lalu membaca stok pabrik untuk barang
pelanggan dan menolak pengambilan yang sah.

**Layar Jasa** (`/jasa`, pintu ke-14, ikon `◇` — Geometric Shapes, bukan emoji)
tempat MENAMPILKAN: pesanan lahir di Pos Timbang, jadi tak ada tombol "buat
pesanan". Ia ada justru karena saringan stok membuang barang pelanggan dari
setiap layar stok — tanpa halaman ini barang orang lain memakan silo tanpa
terbaca di mana pun. **Nota** `jasa.nota_jasa()`: bobot & milik saja, bekatul di
LUAR "Total kembali" dan per proses sosoh, selisihnya SATU baris yang mengaku
tidak diukur terpisah.

Uji ketaatannya `tests/pg/test_jasa_ketaatan.py` (29 uji, 8 bagian).

⚠⚠ **"JASA?" DITENTUKAN `timbangan_transaksi.jasa` (migrasi 0066/0041 di repo
`timbangan`), BUKAN `pelanggan_id IS NOT NULL`.** Cacat lapangan 2 Oktober
2026 — pemilik melihat langsung di layar Stok: lot PK titipan pelanggan
tercatat sebagai pembelian pabrik, pemasok PALSU ("MARNOOO") ikut lahir.

Akarnya: borang jasa Pos Timbang SENGAJA punya pintu ketik-bebas untuk
pelanggan baru yang belum sampai ke cermin Kledo (`_wajib_pihak`: "boleh dari
daftar ATAU diketik bebas"). Saat nama diketik bebas, `pelanggan_id` yang
terkirim TETAP KOSONG — `_pasang_pihak(trx, arah, pihak_id=None, jasa=True)`
mengosongkan KEDUA kolom FK, sebab `pihak_id`-nya memang belum ada id sampai
`purchase.find_or_create_pelanggan` membuatnya DI PRODUKSI. Baris tiket
"jasa-pelanggan-baru" jadi IDENTIK bentuknya dengan "pembelian-pemasok-baru":
tak ada apa pun yang membedakan keduanya tanpa penanda tersendiri.

`adalah_jasa()` kini membaca `t.jasa` sebagai PENENTU UTAMA, dengan
`pelanggan_id`/`jasa_id` sebagai kaki kedua (untuk tiket LAMA dari sebelum
kolomnya ada — migrasinya membackfill dari situ). `nama_pihak()` punya cacat
KEMBAR yang terpisah: ia memeriksa `nama_pelanggan`/`pelanggan_id` sendiri,
jadi kartu antrean untuk pelanggan-baru-ketik-bebas menampilkan nama telanjang
TANPA tanda "JASA" walau `adalah_jasa()` sudah benar — keduanya dibetulkan
dan diuji terpisah, sebab satu bisa benar tanpa yang lain.

⚠ KOLOM `jasa` MILIK RANTAI REPO `timbangan` (migrasi 0041 di sana), dan 0066
di repo ini cuma menambahkannya IDEMPOTEN — pola yang sama persis dengan
`pelanggan_id` di 0064. Downgrade 0066 TIDAK menjatuhkannya: menjatuhkan dari
sini akan merobohkan Pos Timbang di repo sebelah.

Satu pelajaran metodologis: `tests/timbangan/test_jasa_masuk.py` SUDAH punya
`test_pemilik_boleh_diketik_bebas` sebelum cacat ini ditemukan, dan ia sudah
membuktikan `(supplier_id, pelanggan_id) == (None, None)` sebagai perilaku
yang BENAR — tetapi tak pernah memeriksa apakah jejak itu masih bisa dibaca
BENAR oleh pembaca lain (produksi, basis data yang sama). Menguji bahwa
sebuah pintu bekerja tidak sama dengan menguji bahwa akibatnya di seberang
pintu itu benar.


## Sub-menu Antrian tunggu — grup, dan jaring yang menangkap sisanya

Keputusan pemilik 2 Oktober 2026: *"antrian tunggu bisa banyak sekali"* →
*"bisa tidak antrian tunggu jika di klik muncul dropdown sub menu?"* → *"sub
menu pertama bahan baku, kedua tunggu packing. tunggu dipindah."*

Pintu "Antrian tunggu" di laci berubah jadi `<details>` saat ada **≥2 grup
berisi**: kliknya membuka sub-menu, bukan menuju halamannya. Karena itu baris
pertama sub-menu WAJIB **"Semua"** — tanpanya daftar utuh jadi tak terjangkau
dari laci. Dengan satu grup, pintunya kembali jadi tautan biasa: dropdown tanpa
pilihan merampas satu ketukan. Syaratnya SAMA dengan syarat pil di halaman,
supaya laci berdropdown tak pernah berdiri di atas halaman tanpa pil.

Di dalam halaman, grupnya jadi pil `?grup=` (alamat, bukan jangkar: yang
dibutuhkan MENGURANGI apa yang terlihat, bukan menggulir). `?grup=` ngawur →
tampilkan semuanya, bukan 422. Grup yang kosong berkata **"Grup ini kosong"**
berikut jalan keluarnya — BUKAN "Tidak ada yang menunggu Anda", kalimat yang
menyuruh orang pulang padahal tiga grup lain berisi.

⚠ **`grup_baris()` berkunci pada `aksi`, BUKAN `kelompok`.** `kelompok` sudah
dipakai untuk tiga blok DI DALAM halaman, dan ia RANCU untuk ini:
`kelompok="tumpukan"` berarti "gabah menunggu giliran giling" di Gudang 1
(bahan baku) dan "PK menunggu dipindah ke silo" di Gudang 2 (tunggu dipindah).
Satu nilai, dua grup. `aksi` tidak rancu — ia memang menyebut apa yang
DITUNGGU. Kartu DIAM (tanpa `aksi`) jatuh ke `kelompok` sebagai kaki kedua.

⚠ **GRUP TERAKHIR ("Lainnya") KOMPLEMEN, bukan daftar.** Apa pun yang tak
terpetakan jatuh ke sana — termasuk jenis kartu yang lahir besok. Hari ini
isinya perintah muat barang keluar dan penyosohan yang menunggu verifikasi
Admin: dua hal yang pemilik belum beri nama grup. Daftar yang harus lengkap
adalah daftar yang suatu hari tidak, dan kartu yang tak masuk grup mana pun
akan HILANG dari layar yang menagihnya. Invarian yang menjaganya:
**Σ grup == panjang antrean** (`tests/test_grup_antrean.py`).

⚠ Nama `aksi` yang salah tulis jatuh DIAM-DIAM ke "Lainnya" — tiga sempat
salah tulis saat petanya ditulis. Dijaga dengan membandingkan peta terhadap
`aksi=` yang sungguh ada di `berjalan.py`.

`SUBMENU` disusun `Berjalan.submenu()` dan ikut `lencana()` — satu benda untuk
seluruh laci, sebab laci yang berbeda antar-layar dibaca sebagai "pekerjaannya
sudah habis". Di `base.html` ia DIGERAKKAN DATA (`SUBMENU.get(kunci)`), bukan
`if kunci == 'aksi'`: berkas itu milik bersama beberapa aplikasi.

⚠⚠ **GRUP YANG `aksi`-NYA SAMA TAPI PEMILIKNYA BEDA BUTUH SUMBU KETIGA.**
Keluhan pemilik 6 Oktober 2026: *"di halaman tunggu packing tidak bisa
dibedakan mana jasa mana yang tidak."* Kartu beras titipan pelanggan dan
kartu beras pabrik yang sama-sama belum dikemas memakai `aksi="catat_packing"`
IDENTIK — sheet yang dibukanya memang sama — jadi pernyataan di atas ("`aksi`
tidak rancu") tetap benar untuk PEKERJAAN, tapi tak menjawab PEMILIK. Grup
`"packing_jasa"` ("Packing jasa") ditambahkan dengan cabang KHUSUS di
`grup_baris()`, DIPERIKSA SEBELUM `_GRUP_AKSI`: `aksi=="catat_packing" and
b.jasa_id is not None → "packing_jasa"`. `Baris` dapat field baru `jasa_id`
untuk ini — bukan menambah entri `_GRUP_AKSI` (yang kuncinya `aksi`, satu
nilai per kartu, tak bisa membedakan dua kartu ber-`aksi` sama).

Kartunya sendiri (`_kartu_beras_curah`, `app/services/berjalan.py`) juga
menyebut pemiliknya di `sub` (`· TITIPAN <nama>`, pola yang sama dengan
picker `/pk-g1-tersedia` dan `api.py`'s `pk_gudang1`) — grupnya memisahkan,
tapi satu grup masih bisa berisi lebih dari satu pelanggan sekaligus, dan
kartu yang tak menyebut pemiliknya sendiri membuat orang menebak lagi.

Uji: `tests/pg/test_grup_packing_jasa.py` (kartu jatuh ke grup yang benar,
tiga grup pertama tak bergeser, filter `?grup=` lewat HTTP sungguhan).

## Sub-menu "Menunggu keputusan" — PER KATEGORI (sejak 2 Okt 2026)

Permintaan pemilik: *"lakukan yang sama ke menunggu keputusan"* — diperjelas
*"maksud saya buat sub menu juga sesuai kategori."* Mekanisme lacinya sama
persis dengan Antrian tunggu — `<summary>` tanpa navigasi, ≥2 kategori
berisi untuk menawarkan dropdown, pil `?kategori=` di dalam halaman, kalimat
"Kategori ini kosong" yang dibedakan dari "Tak ada yang menunggu keputusan".

⚠ **"Kategori" di sini PER JENIS, bukan golongan kasar.** Percobaan pertama
mengelompokkan lewat `services/keputusan.GOLONGAN` ("permintaan" menggabung
DUA jenis: `acc_permintaan_pk` dan `tutup_permintaan_pk`) — dan itu bukan
yang diminta. `GRUP_KEPUTUSAN`/`grup_keputusan()` sekarang **diturunkan dari
`keputusan.blok(mutu=False)`**, sumber yang SAMA yang menggambar blok
halaman `/keputusan` sendiri (`JENIS_KEPUTUSAN`) — jadi kategori sub-menu
dan blok halaman menunjuk hal yang persis sama, satu per satu, dengan nama
yang sama (tak ditulis ulang tangan; peta `_GRUP_AKSI` di Antrian tunggu
sempat salah ketik TIGA nama aksi sebelum ketahuan).

⚠⚠ **KATEGORI MUTU TAK PERNAH MASUK `GRUP_KEPUTUSAN`.** Mutu punya
layarnya sendiri (`/mutu`, keputusan pemilik 24 September 2026); kategori
mutu di sub-menu ini akan menjanjikan pekerjaan yang tak pernah digambar
di halaman ini. `jumlah_grup_keputusan()` melompati baris mutu secara
eksplisit sebelum menghitung — `self.meja` membawa KEDUANYA bercampur,
pemisahannya baru terjadi saat render `/keputusan` vs `/mutu`.

Alamatnya `?kategori=`, bukan `?grup=` (nama mengikuti kata pemilik) dan
bukan `?golongan=` (percobaan pertama yang dicabut). Jaring "Keputusan lain"
di `keputusan.html` tetap bekerja sama seperti sebelumnya saat kategori
dipilih "lain" atau tak dipilih; memilih kategori lain mengosongkannya
dengan sendirinya (item yang dikenal selalu ADA di `AKSI_DIKENAL`).

Uji: `tests/test_grup_keputusan.py` (13 — grouping dibandingkan LANGSUNG
terhadap `K.blok(mutu=False)`, render pil, render laci) dan
`tests/pg/test_grup_keputusan_http.py` (3 — jalur HTTP sungguhan lewat
fixture `permintaan_pk` naik sampai `kirim()`, membuktikan `?kategori=` dan
laci terhubung ke agregasi `svc.untuk()` yang sesungguhnya, dan membuktikan
"Permintaan lot PK dari Gudang 2" vs "Kiriman PK menunggu ditutup" memang
dua kategori terpisah begitu satu permintaan berjalan sampai tahap kirim).

⚠ Pelajaran selector uji: `'<a class="pil'` longgar — kartu SUNGGUHAN
("Setujui/Tolak permintaan") merender `class="pilihan__satu"` sebagai
`<a>`, diawali huruf sama. Penanda yang aman untuk `keputusan.html`:
`'<div class="saring">'` (halaman ini tak punya fitur lain berkelas itu —
beda dari `aksi.html`, yang memakainya untuk kotak cari).

⚠⚠ **`verifikasi_keluar` TERDAFTAR di `K.JENIS` sejak 2 Oktober 2026** —
sebelumnya TIDAK, dan itu laporan lapangan kedua: pemilik melihat dua blok
("1. Verifikasi Muatan", "2. Pemindahan PK") tetapi sub-menunya tak muncul.
Akarnya: muatan barang keluar yang menunggu diverifikasi Admin (lahir
`_kartu_barang_keluar`, fitur Barang Keluar 28 September 2026) tak pernah
didaftarkan ke taksonomi `services.keputusan.JENIS` — persis pola yang
dokumen modul itu sendiri peringatkan di kepalanya untuk TIGA jenis pertama
("ada di data tetapi tak digambar di layar mana pun"). Kartunya jatuh ke
jaring "Keputusan lain" DAN ke keranjang "lain" sub-menu — dan kalau item
lain yang menunggu KEBETULAN juga tak dikenal, dua jenis pekerjaan berbeda
bercampur jadi SATU kategori, sehingga syarat ≥2 tak pernah terpenuhi walau
layarnya sudah menampilkan dua blok terpisah. Golongannya "output".

Ikut terungkap: `tests/test_keputusan_lengkap.py` — yang DIRANCANG khusus
menjaga celah persis ini — PUNYA TITIK BUTA yang sama. Pemindaiannya dulu
hanya mencari teks harfiah `b.meja.append(` di seluruh modul; kartu
`verifikasi_keluar` lahir di fungsi pembantu (`_kartu_barang_keluar`) lewat
variabel LOKAL (`keluar.append(Baris(...))`, bukan `b.meja.append(...)`),
baru digabung ke `b.meja` di titik panggilnya (`b.meja += await
_kartu_barang_keluar(..., untuk_admin=True)`). Pola yang memindai teks
persis berhenti bekerja tepat pada bentuk yang sedikit berbeda. Diperbaiki:
`_aksi_yang_dikirim_ke_meja()` kini MENGIKUTI setiap `b.meja += await
<fungsi>(`, membaca sumber fungsi itu sendiri lewat `inspect`, dan memindai
accumulator APA PUN namanya — dengan satu penyempitan penting: fungsi yang
melayani DUA TUJUAN lewat satu bendera (`untuk_admin`) hanya dipindai pada
CABANG yang sesuai (lewat indentasi), supaya aksi milik cabang lain
(`muat_semua`, yang berakhir di `b.menunggu`) tak ikut tertagih salah arah.

Uji mutasi: `verifikasi_keluar` dicabut sementara dari `K.JENIS` — penjaga
yang diperbaiki menangkapnya dengan pesan galat yang sama persis seperti
seharusnya muncul sejak 28 September. Reproduksi lapangan langsung:
`test_verifikasi_muatan_dan_permintaan_pk_dua_kategori_terpisah` di
`tests/pg/test_grup_keputusan_http.py` — barang keluar sungguhan (packing →
perintah → muat) berdampingan dengan permintaan PK sungguhan, lewat HTTP.

## ⚠ Kelas CSS karangan: tidak melempar galat, cuma tak menggambar

Dalam dua hari ENAM kelas karangan lolos ke layar Jasa — `pil--aktif`
(`pil--on`), `btn--halus` (`btn--kecil`), `kartu__judul`, `lencana--netral`
(`.lencana` tanpa pengubah memang yang netral), `redup` (`bantu`), `blok`.
Tak satu pun melempar apa pun. Dan satu tombol MATI: "Tutup pesanan" memakai
`data-post` tanpa `data-kirim`, sementara `aksi.js` mengikat
`closest("[data-kirim]")` — ia diam total saat ditekan, tanpa galat, tanpa
kabar.

Dijaga `tests/test_grup_antrean.py`: setiap `class="…"` murni di
`app/web/templates/` wajib ada di `app.css`, dan setiap `<button data-post>`
wajib ber-`data-kirim`. Keduanya membuang komentar Jinja dulu — komentar repo
ini sering mengutip markup yang salah berikut sebabnya, dan penjaga yang
memerah karena kutipan akan dilonggarkan orang yang tergesa.

**Sebelum memakai nama kelas, cari dulu di `hmu_tampilan/static/app.css`.**

## Riwayat sosoh — neraca bobot, 100% tanpa sisa (sejak 2 Oktober 2026)

Pintu ke-15 (`/riwayat-sosoh`, ikon `◭`). Keputusan pemilik: kartu tiap
penyosohan **yang selesai**, dan *"terkhusus berapa persen yang jadi beras,
berapa persen broken, berapa persen menir, berapa persen bekatul, lalu berapa
persen susut debu/bobot."*

    bahan  = PK TERPAKAI seluruh silo (awal + ditambah − sisa)
    keluar = beras + SELURUH hasil samping
    susut  = bahan − keluar
    persen = bagian / bahan × 100

Contoh pemilik sendiri: bahan 10.000 kg, keluar 9.900 kg → susut 1%.

⚠ **Penyebutnya `berat_terpakai_kg`, bukan `berat_awal_kg`** — "termasuk
campurannya". Silo yang dipoles boleh diisi lagi (keputusan 12 Sep 2026), dan
PK yang masuk di tengah proses ikut jadi bahan baku. Memakai berat awal membuat
susut terbaca jauh lebih besar daripada sebenarnya, dan susut dipakai menilai
mesin dan orang.

⚠ **SELURUH persen berpenyebut SAMA, dan itu yang membuat jumlahnya tepat
100%.** Baris "Jumlah" di kaki kartu bukan hiasan: satu entri hasil yang salah
ketik langsung menggeser susutnya, dan di sanalah ia terbaca tanpa seseorang
perlu mencurigainya lebih dulu. `reject` tak pemilik sebut tetapi tetap
DIJUMLAH — membuangnya memindahkan beratnya ke susut, dan susut adalah angka
yang dipakai menuduh mesin bocor. Jenis samping baru pun ikut terjumlah
sendiri: daftar sisanya dibaca dari `BYPRODUCTS`, tak ditulis tangan.

Rumusnya **murni** di `polishing.neraca_sosoh(pk_terpakai, outputs)` — tanpa
basis data, supaya kasus tepinya bisa diuji atas angka telanjang
(`tests/test_neraca_sosoh.py`). Dan `rendemen()` dipisah jadi rumus murni juga;
`rendemen_proses()` serta `KartuSosoh.rendemen` dua-duanya memanggilnya. Dua
jalan yang kebetulan sepakat akan berselisih begitu salah satunya disentuh —
dan yang berselisih di sini angka yang menilai pekerjaan orang.

Dua keadaan yang **dilaporkan, bukan disembunyikan**:

  · **susut negatif** (hasil melebihi bahan) = mustahil secara fisik, jadi
    selalu salah catat. TIDAK dipangkas jadi 0%: yang dipangkas tak pernah
    terbaca, dan yang tak terbaca tak pernah dibetulkan. Batang neracanya pun
    tak digambar;
  · **bahan nol** → persennya `None`, bukan 0%. Nol persen adalah pernyataan
    bahwa tak ada yang jadi; yang benar "tak bisa dihitung".

⚠ **Tak ada ambang "susut terlalu besar".** Pemilik belum menetapkannya, dan
pagar yang ditebak sendiri menuduh mesin yang sehat — aturan yang sama dengan
batas ton di layar Jasa.

**HANYA yang selesai.** `status="selesai"` dijamin seluruh silonya sudah
ditandai (`selesai_penyosohan`), jadi penyebutnya pasti. Proses berjalan punya
pintunya di `/berjalan`, dan persen dari hasil yang masih bertambah akan dibaca
sebagai hasil akhir.

**Pintunya Super Admin, Admin, operator Gudang 2** (keputusan pemilik) —
ditulis sebagai `(SUPER, ADMIN, POLESAN)` di `nav.TAB`, bukan `None` +
`PINTU_MATI`: daftar yang BOLEH tak perlu disunting tiap kali view baru lahir.
⚠ Rutenya menjaga sendiri lewat `_is_g2_operator`; menyembunyikan pintu bukan
penjagaan.

ENAM kueri, berapa pun banyak kartunya (tujuh bila ada kartu jasa). Dijaga
sebagai PERBANDINGAN satu-kartu vs enam-kartu, bukan langit-langit: N+1 yang
kebetulan kecil tetap lolos dari langit-langit. Halamannya memakai KURSOR
(`?sebelum=<id>`), bukan nomor halaman — riwayat bertambah di ujung yang sama
dengan arah bacanya.

## Bobot bahan: nota vs timbangan (sejak 25 September 2026)

    real = berat BARANG menurut Pos Timbang (netto − tara karung)
    kurang = nota − real
    kurang <= toleransi  → NOTA   ·  toleransi = 0,2% nota untuk GABAH BASAH
    kurang >  toleransi  → REAL   ·              0      untuk selainnya

Sebelumnya nota menang begitu ada, sejauh apa pun timbangan di bawahnya.
Arah kesalahannya selalu sama: gabah tercatat LEBIH BANYAK daripada yang turun
dari truk — stok menggelembung, dan rendemen lot itu terbaca lebih rendah
daripada yang sebenarnya.

Toleransinya PERSEN, bukan kilogram tetap: susut perjalanan tumbuh bersama
muatan (0,2% = tepat 20 kg pada 10 ton, angka yang pemilik sebut). Angkanya di
`setelan_pabrik` → `setelan.toleransi_nota_persen`; JENIS mana yang mendapatnya
di kode → `timbang_link.JENIS_BERTOLERANSI`. Yang tak disebut mendapat 0.

SATU aturan, DUA bentuk yang wajib sepakat — `timbang_link.bobot_efektif`
(Python, dipakai layar) dan `SQL_BERAT_TIKET` + `SQL_SUMBER_BERAT` (dipakai
poller & rekonsiliasi, keduanya butuh bind `:tol_persen`).
`tests/pg/test_bobot_nota.py` mengadu keduanya atas 15 kasus — jangan menyalin
rumusnya ke kueri ketiga.

`sumber_berat` dihitung dari ATURAN, bukan dari "ada nota": sesudah hari ini
ada nota tak lagi berarti nota yang dipakai. Saat nota kalah, kartunya
menyebut sebabnya ("nota 10.000 kg, kurang 300 kg > batas 20 kg") — itu angka
yang dipakai orang menelepon pemasoknya.

Data lama TIDAK dihitung ulang: aturan ini untuk pencatatan baru.

## Silo broken — satu wadah, dua arah, satu pemilik (sejak 6 Oktober 2026)

Keputusan pemilik: broken (PK yang sudah disosoh, patah) bisa disosoh ULANG
sebagai bahan baku — dan jalan paling murah untuk itu bukan mencatat "jenis
bahan" per pemakaian silo, melainkan memberi broken SILONYA SENDIRI.
`Silo.jenis_isi` ('pk' default / 'broken') kini di master (`hmu_core`,
migrasinya DI PRODUKSI — lihat catatan di `migrations/versions/
0071_silo_jenis_isi.py` untuk kenapa, bukan di chain core yang belum jadi
pelari sungguhan). Dari sinilah campuran bahan sebuah proses sosoh
DITURUNKAN dari silo sumbernya — `PolishingSiloUsage` sendiri SILO-AGNOSTIK,
jadi `mulai_penyosohan`/`selesai_penyosohan`/`rendemen_proses` memakai silo
broken tanpa satu baris kode pun berubah di sana.

**Segregasi WAJIB, dua arah.** PK tak boleh masuk silo broken
(`_tujuan_and_silo`, `pindah_tumpukan_ke_silo` menolak), broken tak boleh
masuk silo PK (`pindah_broken_ke_silo` menolak) — wadahnya yang membedakan,
bukan catatannya. `hitung_stok_silo` bercabang menurut `jenis_isi`:
silo PK memakai rumus lama (masuk langsung + tumpukan − terpakai); silo
broken memakai `_hitung_stok_silo_broken` (masuk dari `broken_ke_silo` −
terpakai) — tak punya jalan "langsung" sama sekali.

**Broken jadi baris sebelum bisa dipindah.** `catat_broken` (sebangun
`catat_bekatul`) menulis `byproduct_stock` (jenis_produk='broken') — langkah
WAJIB sebelum `pindah_broken_ke_silo` (tabel `broken_ke_silo`, sebangun
`pk_tumpukan_to_silo`) bisa memindahkannya ke silo broken. ⚠ BEDA dari
bekatul: `jasa_id` DIISI di sini (broken KEMBALI ke pelanggan — keputusan
pemilik 12; hanya sekam & bekatul yang ditahan), dan DISALIN ke
`broken_ke_silo` dari baris sumbernya — pola yang sama dengan
`masukkan_pk_luar`, supaya broken pelanggan tak diam-diam berubah jadi
broken pabrik tepat saat dituang. `pemilik_silo_g2` ikut membaca
`broken_ke_silo` sebagai jalan masuk KETIGA (selain intake langsung & lewat
tumpukan) — tanpanya silo broken selalu terbaca "milik pabrik".

⚠ Keduanya (`pindah_broken_silo` & `catat_broken`) TIDAK lewat jalur
peristiwa (Tahap 3) — owner tak memintanya di jalur itu, sama seperti
`tutup_silo_giling`. Belum bisa di-undo; label-nya tetap ada di
`undo._TABLE_LABEL` untuk List Audit.

⚠⚠ **STOK CURAH BROKEN TIGA SUKU, BUKAN DUA.** `hitung_stok_broken_curah` =
masuk (`byproduct_stock`) − keluar (`OutgoingItem` byproduct_curah) −
TERPAKAI (dipindah ke silo, `broken_ke_silo`). Tanpa suku ketiga, broken
yang sudah dipindah ke silo (dan mungkin sudah disosoh ulang) tetap
terhitung sebagai stok curah yang bisa dijual. Pola yang sama berlaku di
`beras_curah()` (kartu Stok Produk): `_broken_dibukukan` (sebangun
`_bekatul_dibukukan`) menggabung yang dikarungi DAN yang dicatat curah
supaya broken yang sudah punya rumah tak tampil lagi sebagai "belum
dikemas" selamanya.

⚠ **Pagar: proses tak boleh memakan broken yang ia hasilkan sendiri**
(`pindah_broken_ke_silo`) — fisiknya mustahil (broken keluar di ujung mesin),
tetapi data tak mencegahnya begitu jalur masuk broken ada: operator bisa
mencatat hasil lalu memindahkannya ke silo yang SEDANG dipakai proses yang
sama, sebelum prosesnya ditutup. Ditolak dengan membandingkan `source_id`
baris broken terhadap `PolishingSiloUsage` yang masih terbuka pada silo
tujuan.

⚠ **Pagar yang SAMA, arah TERBALIK** — `tambah_silo_penyosohan` (11 Oktober
2026, laporan lapangan: operator ingin menambah broken yang sudah ada di
silo sebagai CAMPURAN BAHAN ke proses sosoh yang berjalan, bukan menyimpan
hasil broken). Pagar di atas tak menghadang urutan ini: broken proses P
dipindah ke Silo X SEBELUM X jadi bahan P (saat itu X belum jadi sumber,
jadi pagar `pindah_broken_ke_silo` diam), lalu P mencoba memakai X sebagai
bahan BARU lewat "Tambah silo (mix bahan)". `tambah_silo_penyosohan`
menolak begitu Silo X punya SATU baris `broken_ke_silo` pun yang menunjuk
balik ke `proc.id` — diperiksa lewat riwayat pemindahan, bukan "stok silo
saat ini", dan menolak silonya UTUH (bukan mencoba memisah bagian yang
"aman", sama konservatifnya dengan `pastikan_satu_pemilik`). Picker
`/actions/silo-bahan-g2` sendiri SENGAJA tak menyaring `jenis_isi` (PK,
broken, Beras semua bisa jadi bahan — `PolishingSiloUsage` silo-agnostik)
dan juga TAK memeriksa pagar ini: ia tak tahu proses mana yang akan
ditambahi (field `kode` di atasnya tak terhubung sebagai `induk` — borang
`remote_banyak` belum mendukungnya), jadi picker boleh menawarkan silo yang
kemudian ditolak layanannya — pola yang sama yang sudah diterima untuk
`mulai_penyosohan`.

**Rendemen atas SELURUH bahan**, bukan PK saja — sama dengan lot KS/MIX
Gudang 1. Karena `PolishingSiloUsage` tak peduli isi silonya, penyebut
`rendemen_proses` (sum `berat_terpakai_kg` seluruh usage) SUDAH otomatis
menjumlah PK + broken begitu kedua jenis silo ikut dalam satu proses — tak
ada kode tambahan yang perlu menjaga ini secara eksplisit, tetapi jangan
sampai ada pembaca baru yang menjumlah "PK terpakai saja" untuk penyebut
rendemen proses campuran: angkanya akan terbaca lebih bagus daripada yang
sebenarnya, sebab sebagian bahannya sudah pernah disosoh.

⚠⚠ **`sisa_jasa()` dan "terhitung dua kali".** Broken milik pesanan jasa
yang sudah dicatat curah ATAU sudah dipindah ke silo broken (belum disosoh
ulang) dihitung SisaJasa.`broken_kg` = masuk `byproduct_stock` − terpakai
(`PolishingSiloUsage` pada silo ber-`jenis_isi='broken'`). Suku `broken_ke_
silo` itu sendiri SENGAJA tak dikurangkan langsung — ia menelusup
("telescoping"): dikurangkan di satu sisi (jalan masuk silo), ditambahkan
balik di sisi lain (jalan keluar curah), sehingga totalnya tetap benar
selama barangnya baru BERPINDAH TEMPAT, dan baru berkurang betul-betul saat
sungguh disosoh ulang (`berat_akhir_kg` terisi). Tanpa ini broken yang sudah
dipindah ke silo terhitung dua kali: sekali di sini, sekali lagi sebagai
hasil barunya begitu disosoh ulang.

**Silo Gudang 2 kini bisa ditambah dari UI** (`Pengaturan → Alat`) —
sebelumnya TIDAK bisa walau beberapa kalimat di kode sudah menjanjikannya
("Belum ada silo Gudang 2. Tambahkan di Pengaturan → Alat"); borangnya cuma
pernah dibangun untuk silo gabah kering Gudang 1. `jenis_isi` ditetapkan
SEKALI saat silo dibuat — tak ada borang untuk menggantinya, sebab campur
PK/broken dalam satu silo tak boleh terjadi sama sekali.

Uji: `tests/pg/test_silo_broken.py`.

## Stok Produk — barang jasa, dan saringan yang ada di tempat yang salah (6 Oktober 2026)

Sebelum perbaikan: PK Gudang 1 & Gudang 2 sudah menampilkan barang jasa
(`LotPk`/`LotPkG2`, berikut `pemilik`) di kartu stoknya; Stok Produk
membuangnya di SUMBERNYA — `FinishedGoodsStock.jasa_id.is_(None)` di
`stok.barang_jadi_g2()`. Akibatnya operator yang memandang 40 karung beras
pelanggan di gudang membuka Stok Produk dan melihat kosong — padahal
komentar di sisi PK, di berkas yang SAMA, sudah menetapkan aturannya:
daftar stok yang menyembunyikan barang titipan berselisih dengan yang
dilihat orang di gudang, dan yang TIDAK boleh cuma satu hal — ia ikut ke
borang yang MENJUAL. Itu disaring di TEMPAT PEMAKAIANNYA, bukan di sumber
datanya.

**`barang_jadi_g2()` kini mendaftar PABRIK *dan* TITIPAN**, kuncinya ikut
`jasa_id` (bukan cuma SKU × mutu — 40 karung Bu Sri tak boleh menyatu
dengan karung pabrik jadi satu baris), tiap kartu membawa `jasa_id` dan
`pemilik`, sebangun `LotPk`. ⚠ KECUALI BEKATUL: `jasa_id`-nya NULL sejak
dibukukan (beralih milik, keputusan pemilik 12) — itu TETAP, blok bekatul
curahnya tak disentuh.

⚠⚠ **EMPAT PEMAKAI, DUA JENIS GERBANG — dan keduanya wajib benar bersamaan.**
Yang memberi makan borang PENJUALAN wajib menyaring `jasa_id is None`
sendiri, persis pola PK (`aksi_inventory.barang_bisa_keluar` membuang
`l.jasa_id is not None` untuk PK; sekarang begitu juga untuk SKU barang
jadi):

  · `aksi_inventory.stok_barang_jadi` — JUAL, disaring.
  · `aksi_inventory.barang_bisa_keluar` — JUAL, disaring.
  · `layar_produk.halaman_stok_produk` (`/stok-produk`) — TAMPIL, tetap
    PABRIK saja (disaring KELUAR dari `kemasan`, sebab kepala kartunya dari
    `stok_produk()` yang juga pabrik-saja; mencampur keduanya akan membuat
    rincian kemasan menjumlah lebih besar daripada kepala kartunya).
  · `layar_produk.halaman_stok_produk_jasa` (`/stok-produk-jasa`, BARU) —
    TAMPIL, titipan SAJA, dikelompokkan per `jasa_id` ("pisahkan per
    pelanggan pemilik barang" — permintaan pemilik).

Melewatkan satu pemakai JUAL saja berarti beras pelanggan muncul di borang
penjualan pabrik — kerusakan yang tak terlihat sampai ada yang menjualnya.

**Halaman baru `/stok-produk-jasa`** masuk sub-menu "Stok" sebagai tujuan
ketiga (`nav.TAB` + `Berjalan.submenu()`/`lencana()`, mengikuti pola
`stok_produk` persis: selalu `PINTU_MATI`, berdiri sendiri di laci). Satu
seksi per pesanan jasa; angkanya 0 di sub-menu (murni informasi, sama
dengan "Stok PK").

⚠⚠ **KARTUNYA WAJIB RUPA YANG SAMA DENGAN `/stok-produk`** — permintaan
pemilik susulan: *"tampilannya juga harus konsisten seperti kartu stock
milik kami sendiri."* Kartu sederhana (nama + kg saja) DICABUT; halaman ini
sekarang memanggil `stok.stok_produk(db, jasa_id=...)` — fungsi yang SAMA
yang memberi makan `/stok-produk`, bukan cuma `barang_jadi_g2()` — sehingga
kartunya punya empat suku (`Hasil sosoh`/`Keluar`/`Dikemas`/`Curah`) dan
laci FIFO yang sama persis. Makronya sendiri (`blok`) pindah dari
`stok_produk.html` ke `_stok.html` supaya kedua halaman menggambar dari SATU
definisi, bukan dua salinan yang akan berselisih pada perubahan berikutnya.

⚠ **`stok_produk()` kini menerima `jasa_id`** (bawaan `None` = PABRIK,
`PolishingProcess.jasa_id IS NULL`) — dan ini MEMBETULKAN cacat yang
sebelumnya tersembunyi: fungsinya dulu TIDAK menyaring proses sama sekali,
jadi "hasil sosoh" dan "curah" pabrik diam-diam memuat output proses jasa.
Begitu juga kueri "keluar" (`OutgoingItem`/`OutgoingRecord`) kini ikut
disaring `OutgoingRecord.jasa_id` — pengambilan jasa lewat rantai yang sama
dulu ikut mengurangi "keluar" pabrik. Bekatul TETAP dikecualikan dari jalur
`jasa_id` terisi (lihat docstring fungsinya): ia tak pernah "milik satu
pesanan".

Uji: `tests/pg/test_stok_produk_jasa.py` (termasuk pagar isolasi pabrik vs
jasa di `stok_produk()`, dan satu uji HTTP penuh yang menggambar halamannya
sungguhan — pelajaran `TempatPk.pemilik`: penjaga yang cuma memanggil
fungsinya lulus pada hari templatnya berhenti menggambar angkanya).

⚠⚠ **DIKELOMPOKKAN PER PELANGGAN (`Jasa.pelanggan_id`), BUKAN PER PESANAN
(`Jasa.id`)** — koreksi lapangan: *"pemisahannya bukan per proses. tapi per
pelanggan."* "SATU PESANAN, BEBERAPA KEDATANGAN" (docstring `Jasa`) berarti
kedatangan ULANG dari pelanggan yang sama melahirkan `Jasa` BARU — jadi
mengelompokkan per `jasa_id` memecah barang SATU pelanggan jadi beberapa
seksi, persis kebalikan dari yang diminta. `stok_produk()` karena itu
menerima `jasa_id` sebagai DAFTAR (`int | list[int] | None`) — seluruh
pesanan pelanggan yang sama disatukan dalam SATU panggilan (`k.jasa_id.in_
(...)`), bukan digabung belakangan dari beberapa `KartuProduk` terpisah.
Judul seksinya pun `Pelanggan.nama_pelanggan` apa adanya ("Bu Sri"), BUKAN
`jasa.nama_pemilik()` yang menyebut kode pesanan ("JAS-2610-001 Bu Sri") —
kode pesanan tunggal akan salah begitu seksinya mewakili dua pesanan atau
lebih.

## Kartu Penyosohan gabungan silo — potongan ganda yang didiamkan (6 Oktober 2026)

Laporan lapangan: *"silo ditambahkan lagi beberapa, tetapi tidak tercatat,
yang tercatat hanya 5 kali awal masukan pk."* BUKAN kegagalan mencatat —
PK-nya tetap masuk basis data dan tetap terhitung di fakta "Ditambah"
(`PolishingSiloUsage.berat_masuk_kg`, dijumlah dari SELURUH baris, tak
pernah dipotong). Yang rusak murni TAMPILAN daftar asalnya, dan rusaknya
dua lapis sekaligus.

`_isian_silo()` (dipakai kartu silo TUNGGAL, `_kartu_silo_g2`) sudah benar
sejak awal: ia membatasi `BATAS_ASAL` (6) baris PER SILO tetapi menghitung
sisanya di `IsianSilo.lebih`, disebut lewat `_nota_isian()` ("+N asal lagi
tak ditampilkan"). `_kartu_penyosohan_g2` — kartu GABUNGAN, dipakai saat
satu proses sosoh memakan lebih dari satu silo sekaligus ("Silo B + Silo
A") — memanggil `_isian_silo()` per silo lalu MEMBUANG `.lebih`-nya, lalu
memotong LAGI daftar gabungannya (`asal_pr[:6]`) tanpa `_nota_isian`
maupun padanannya sama sekali. Dua silo × enam baris tiap isian yang
sudah dipotong sendiri-sendiri, dipotong SEKALI LAGI jadi enam — dan
operator yang menuang lebih dari lima-enam kali membaca kartunya seolah
berhenti mencatat.

Perbaikannya: `asal_lebih` menjumlah `.lebih` dari setiap `asal_silo()`
yang dipanggil; `rinci_hasil` (entri hasil) tak lagi dipotong duluan
(`entri[:8]` dicabut); SATU potongan akhir (`_anak_batas = 10`) atas
`rinci_hasil + asal_pr` gabungan, dan sisanya (`asal_lebih` + sisa potongan
akhir) disebut di `nota` kartu — kalimat bentuk yang sama dengan
`_nota_isian`, supaya tak ada dua cara menyebut hal yang sama. `nota`
dijeda tetap menang bila proses sedang berhenti: mesin mati lebih penting
diketahui daripada daftar yang terpotong.

Uji: `tests/pg/test_isian_silo_berjalan.py::
test_kartu_sosoh_gabungan_menyebut_baris_yang_terpotong` (dua silo, delapan
masukan tiap silo — melewati `BATAS_ASAL` DAN batas gabungan sekaligus;
membuktikan "Ditambah" tetap benar dan potongannya tersebut persis).

## Pindah kepemilikan produk jasa — bekatul disebut, sisanya bisa dipindah (6 Oktober 2026)

Keluhan pemilik tentang `/stok-produk-jasa`: *"bekatulnya kenapa tidak ada di
halaman produk jasa? tetap harus ada. tetapi nanti bisa berpindah
kepemilikan menjadi milik kita ... harus ada tombol pindah kepemilikan di
seluruh kartunya. karna bisa jadi produk ataupun hasil samping jadi milik
kita ataupun kita beli."* Lalu koreksi tegas yang membatalkan jawaban
"recommended" semula (pindah penuh): *"admin should typr a kg/karung amount
for a partial transter"* — HARUS sebagian, admin mengetik sendiri jumlahnya.

**Bekatul: disebut, tak pernah kartu.** Ia sudah beralih milik ke pabrik
tepat saat dibukukan (keputusan pemilik 12) — jadi ia tak pernah jadi baris
`stok_produk()` atas nama pelanggan, dan tak pernah dapat tombol (tak ada
kepemilikan untuk dipindah). Ia tetap tampil sebagai baris INFORMASI biasa
(`.kartu`/`.baris`) di tiap seksi pelanggan — pola yang sama dengan "Barang
titipan di gudang" di `/jasa`.

**Pindah kepemilikan: sebagian, FIFO, baris dipecah.** `pindah_kepemilikan_
barang_jadi` (karung, `FinishedGoodsStock`) dan `pindah_kepemilikan_broken_
curah` (kg, `ByproductStock`) ada di `app/penggilingan/inventory/
finished_goods.py`. Admin mengetik jumlahnya; baris TERTUA dipilih dulu
(`ORDER BY waktu, id`, `FOR UPDATE` — dua admin tak bisa memecah baris yang
sama pada detik yang sama), dan baris yang jumlahnya jatuh di TENGAH
dipecah: baris asal dikurangi, baris baru ditulis untuk bagian yang
berpindah (`jasa_id=None`).

⚠⚠ **AMAN walau sebagian sisa pesanan sudah diambil pelanggan atau sudah
dipindah ke silo broken.** Buktinya aritmetika, bukan kebetulan: diberi
`tersedia = masuk − keluar [− terpakai]`, memindahkan TEPAT `jumlah` baris
`masuk` dari `jasa_id=X` ke `jasa_id=None` membuat `tersedia_baru =
tersedia_lama − jumlah` PERSIS — tak peduli baris MANA yang kebetulan
dipilih FIFO, sebab `keluar`/`terpakai` sama sekali tak tersentuh oleh
pemindahan ini. Satu-satunya pagar yang perlu ditegakkan karena itu cuma
`jumlah <= tersedia` SEBELUM memindah — bukan "baris mana yang aman
disentuh".

**Hanya yang SUDAH TERCATAT.** Sebangun `catat_broken` wajib sebelum
`pindah_broken_ke_silo`: hasil mesin yang masih mentah (kolom "curah" di
kartu `stok_produk`, belum dikemas MAUPUN belum dicatat curah) tak punya
baris untuk dipindah — catat dulu lewat "Catat packing" atau "Catat broken
(curah)". Tombolnya karena itu cuma muncul pada baris `kemasan` (sudah
dikemas, `_stok.html`) dan pada baris broken curah yang sudah `catat_broken`
— tak pernah pada kolom "belum dikemas"/"belum dicatat".

⚠⚠ **BROKEN CURAH DIJAWAB & DIPINDAH PER PELANGGAN, BUKAN PER PESANAN** —
pola yang sama dengan koreksi lapangan `stok_produk()` ("pemisahannya bukan
per proses, tapi per pelanggan"). `hitung_stok_broken_curah` kini menerima
`jasa_id: int | list[int] | None`; `pindah_kepemilikan_broken_curah` juga.
Satu pelanggan dengan dua pesanan yang MASING-MASING punya broken curah
wajib menjawab SATU angka gabungan di kartunya — dan tombolnya di
`/stok-produk-jasa` membawa SELURUH `jasa_ids` pelanggan itu
(`nilai=cr:broken|id1,id2`, dipisah koma), bukan cuma pesanan pertama.
Barang jadi berkarung (`bj:`) TAK PERLU ini: `barang_jadi_g2()` sudah
mengunci kartunya per `(sku, std, jasa_id)`, jadi dua pesanan satu pelanggan
selalu tampil sebagai dua baris kemasan terpisah, masing-masing dengan
tombolnya sendiri yang menunjuk SATU `jasa_id` saja.

`jasa_ids_per_pelanggan_dengan_hasil()` (`app/services/jasa.py`) adalah
SATU sumber dipakai BERSAMA oleh `/stok-produk-jasa` (`layar_produk.
halaman_stok_produk_jasa`) dan picker katalog umum (`aksi_inventory.
produk_jasa_tersedia`) — keduanya wajib mengelompokkan pesanan→pelanggan
dengan cara yang SAMA. Tanpa ini, nilai tombol per-kartu (`cr:broken|1,2`)
tak akan pernah cocok dengan satu pun pilihan picker, dan medan "item" di
borang gagal terisi otomatis TANPA SATU PUN GALAT — `aksi.js`
(`isiDariBaris`) mencocokkan nilainya APA ADANYA, bukan menguraikan isinya.

Gerbangnya `can_see_financials` (Admin & Super Admin) — sama untuk tombol,
picker, maupun rute POST-nya (`/api/actions/pindah-kepemilikan-produk`).
Dicatat dengan `aksi="pindah_kepemilikan_produk"` di `log_activity`; belum
lewat jalur peristiwa (Tahap 3) dan belum bisa di-undo lewat List Audit —
label fallback generik yang menanganinya.

Uji: `tests/pg/test_pindah_kepemilikan_produk.py` (FIFO & pemecahan baris
untuk kedua jenis, pagar "aman walau sebagian sudah diambil", pagar
menolak memindahkan lebih dari sisa, picker & tombol yang nilainya cocok
untuk pelanggan dua pesanan, gerbang peran lewat HTTP, dan tampilan bekatul
read-only + broken bertombol di `/stok-produk-jasa`).

## Stok Karung & Karung Jasa — milik KONTAK, bukan pesanan (7 Oktober 2026)

Keputusan pemilik: *"di stok harus punya sub-menu stok karung dan stok
karung jasa"* → *"ubah jadi stok terpisah per pemilik."* Blok "Stok karung"
yang dulu menempel di `/stok` (23 September 2026) pindah jadi dua halaman
sendiri — `/stok-karung` (pabrik) dan `/stok-karung-jasa` (per pelanggan)
— pola "X"/"X Jasa" yang sama dengan Stok Produk/Produk Jasa.

⚠⚠ **ARAHNYA DIBALIK DARI "Pindah kepemilikan produk", DAN PEMILIKNYA
`pelanggan_id` — BUKAN `jasa_id`.** Dua penyimpangan sekaligus dari pola
jasa biasa, keduanya sengaja:

  1. **Arah**: di "Pindah kepemilikan produk", barang MULAI milik jasa
     (diturunkan dari tiket timbang) dan admin mengambil sisa balik ke
     pabrik. Karung TAK PUNYA tiket — `beli_kemasan()` selalu menulis
     pemiliknya `NULL` (pabrik) — jadi satu-satunya arah yang berarti di
     sini KEBALIKANNYA: admin memindahkan sebagian stok pabrik yang sudah
     dibeli MENJADI milik pelanggan, lewat aksi "Pindah kepemilikan
     karung" (`packaging.pindah_kepemilikan_karung`, FIFO baris tertua,
     dipecah bila jatuh di tengah satu baris — mekanismenya sama, cuma
     arahnya dibalik).
  2. **Pemilik**: koreksi pemilik hari yang sama, sesudah jawaban pertama
     (tujuannya pesanan jasa) — *"jalur masuk karung untuk jasa bukan
     berdasarkan proses jasa. tetapi berdasarkan kontak pelanggan."*
     `packaging_purchases.pelanggan_id`/`packaging_losses.pelanggan_id`
     (migrasi 0075, menggantikan `jasa_id` dari migrasi 0074 SEBELUM satu
     baris pun dipakai di produksi) menunjuk `Pelanggan` LANGSUNG, tanpa
     `Jasa` sama sekali — berlawanan dengan aturan "pembandingnya
     `jasa_id`, bukan `pelanggan_id`" di atas (bagian Jasa), dan itu
     disengaja: karung bukan barang yang "dikembalikan" per pesanan
     seperti gabah/PK/beras/broken/bekatul — yang dilacak rekening per
     KONTAK, supaya pelanggan yang datang berulang (`Jasa` baru tiap
     kedatangan) tetap SATU rekening karung.

`hitung_stok_kemasan(pelanggan_id=...)` menyaring KETIGA suku rumus
(beli, hilang, terpakai) — `beli`/`hilang` langsung lewat kolom
`pelanggan_id` yang baru; suku `terpakai` TETAP membaca
`FinishedGoodsStock.jasa_id` (kolom itu tak berubah) dan menerjemahkan
`pelanggan_id` jadi SELURUH `jasa_id` milik kontak itu lewat sub-kueri
`Jasa.pelanggan_id` — satu-satunya titik di mana `Jasa` masih disentuh,
murni untuk mencocokkan konsumsi lintas pesanan pelanggan yang sama.

Picker tujuan tombol "Pindah kepemilikan" adalah `/api/actions/pelanggan-
kledo` (picker KONTAK yang sudah ada, dipakai juga "Buat perintah barang
keluar") — BUKAN `/api/actions/jasa-berjalan`. Picker karungnya sendiri
(`/api/actions/karung-pabrik-tersedia`) berisi KODE/ukuran/merk (sama pola
`kemasan-jenis`), bukan id mentah, supaya tombol per-baris di `_stok.html`
bisa membangun `nilai=` langsung dari field yang sudah ada di
`stok_kemasan_rinci`. ⚠ Merk BOLEH berspasi ("Gunung Mas") — `nilai=`
WAJIB `|urlencode` pada suku merk (pola sama `dasar_borang()`), kalau
tidak nilai mentah di query string memutus pasangan "|" yang dibaca balik
borangnya.

Uji: `tests/pg/test_stok_karung_jasa.py` (rumus tiga suku, FIFO & pemecahan
baris, pagar menolak melebihi stok pabrik, dua pindahan satu pelanggan
digabung, suku `terpakai` lintas seluruh pesanan jasa milik satu
pelanggan) dan `tests/pg/test_stok_karung_http.py` (gerbang peran &
`can_see_financials` lewat HTTP, picker karung & pelanggan cocok dengan
nilai tombol).

## Kode barang

Otoritasnya `app/services/codegen.py`, bukan ingatan:
`GB` pembelian gabah · `PGR` pengeringan · `LOT` giling · `TRF` transfer PK ·
`PKB` beli PK luar · `POL` penyosohan · `PTS` pindah tumpukan · `REJ` PK
ditolak · `OUT` barang keluar · `PKP` beli kemasan · `JAS` pesanan jasa.

`JAS` satu-satunya yang BULANAN (`JAS-YYMM-NNN`, tiga angka): ia menghitung
PEKERJAAN, bukan muatan. Daftar artinya dijaga `tests/test_awalan_kode.py`;
awalan baru wajib didaftarkan di sana.

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
| ~~`pos-produksi-uji` (staging)~~ | **SUDAH TIDAK ADA** (24 Sep 2026). Cabang `origin/uji` masih ada, tetapi tak ada layanan yang menontonnya — `push main:uji` tidak menerbitkan apa pun. Proyek `penggilingan-beras` kini berisi: `penggilingan-beras`, `timbangan`, `kantor`, dan dua Postgres. |
| `kantor` | **`railway up --service kantor`** dari repo `kantor/` — TIDAK tertaut GitHub |
| `timbangan` | repo `timbangan/` |

**App Gudang 2 dan app Meja DIHAPUS 24 September 2026** (keputusan pemilik:
tidak dipakai lagi — operator Gudang 2 maupun staf administrasi memakai Pos
Produksi). Layanan Railway-nya dihapus, repo-nya dihapus, folder lokalnya
dibuang; riwayat keduanya tersimpan sebagai bundel git di
`../arsip/{meja,gudang2}-24sep2026.bundle` (`git clone <bundel>` memulihkannya
utuh). Jangan membangun layar baru di sana, dan jangan menahan perbaikan demi
"menyamakan kedua app".

Dulu: kirim ke uji dulu, tunggu SUCCESS, baru produksi. Selama staging
belum ada lagi, yang menggantikannya: jalankan suite pg, jalankan app-nya di
laptop dan buka layarnya sebagai tiap peran, lalu push `main` dan TUNGGU
deploy-nya SUCCESS sambil memegang commit sebelumnya untuk mundur.

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
