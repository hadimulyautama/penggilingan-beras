# Jasa (toll milling) — irisan pertama, 1 Oktober 2026

Spek pemilik: `QA/SPEK-JASA-FINAL-2026-10-01.md` (menggantikan enam pesan jasa
sebelumnya; keenamnya saling mencabut dan **tidak boleh dipakai**).

## Yang menentukan seluruh bentuknya

**Satu-satunya batasan adalah KEPEMILIKAN.** *"multi silo giling dan multi silo
sosoh memungkinkan. yang tidak memungkinkan adalah menggabungkan barang jika
kepemilikan berbeda. itu saja batasannya."*

**Kedalaman FLEKSIBEL, tidak dinyatakan di muka.** *"jika hanya jadi pk dan pk
ternyata keluar berarti hanya sampai pk."* Karena itu TIDAK ADA kolom
`kedalaman` — sampai mana sebuah pesanan diproses dibaca dari di mana barangnya
sekarang berada.

**Tidak ada batasan ton, di mana pun, dan tidak ada hubungannya dengan biaya.**
*"biaya adalah urusan keuangan. app timbangan dan operasional tidak mengurusi
keuangan."* Jadi tabel `jasa` tanpa kolom harga/tarif/total, dan tak ada ambang
yang memicu peringatan apa pun (permintaan angka kapasitas lantai G2 DICABUT).

**Dua bobot yang tidak ada dan tidak akan ada:** susut sekam (bisa terhisap
penyedot debu) dan bobot gabah setelah dikeringkan (butuh flowing scale, belum
ada). Keterbatasan ALAT, bukan kelalaian pencatatan — jadi permanen sampai
mesinnya ada. Konsekuensi yang harus diingat: untuk lot dari gabah BASAH, "isi
silo" dan "bobot masuk giling" adalah bobot BASAH, dan rendemen KS tak sejenis
dengan rendemen KL.

**Bekatul BERALIH milik, bukan hilang jejak.** Miliknya pabrik, boleh dijual,
tetapi asalnya per proses tetap harus terbaca untuk pemilik barangnya.

## Yang SUDAH dikerjakan (irisan pertama — gabah kering)

Migrasi **0064_jasa**: tabel `jasa`; `jasa_id` pada ENAM tabel
(`purchase_batches`, `drying_lots`, `silo_storage`, `milling_process`,
`internal_transfers`, `pk_gudang2_intakes`); `purchase_batches.supplier_id` jadi
nullable + `CHECK ck_purchase_batches_beli_atau_jasa`;
`timbangan_transaksi.jasa_id` (+ `pelanggan_id` idempoten — lihat jebakan di
bawah).

Penjaga `app/services/jasa.py`, dipanggil di pengering, silo G1, giling, silo G2,
dan pemindahan tumpukan G2 — berkunci basis data, bukan pemeriksaan Python saja.
Saringan `jasa_id IS NULL` di seluruh pembaca stok pabrik & laporan pembelian.
Aliran masuk: `purchase.pesanan_jasa_dari_tiket` membuat pesanan saat operator
menerima tiketnya. Uji: `tests/pg/test_jasa_ketaatan.py` (12 uji).

Rinciannya di `CLAUDE.md` bagian "Jasa (toll milling)".

## Irisan KEDUA — sampai beras, ketiga komoditas (migrasi 0065)

Pemilik menegaskan keputusan nomor 1: jasa dari **gabah basah, gabah kering,
DAN beras PK**. Pembatasan "gabah kering saja" di irisan pertama bukan
permintaannya — ia pembatasan sementara karena dua jalur belum utuh. Keduanya
dibangun di irisan ini:

  · `jasa_id` pada LIMA tabel sisanya (`pk_purchase_batches`,
    `polishing_process`, `finished_goods_stock`, `byproduct_stock`,
    `outgoing_records`) + `pk_purchase_batches.supplier_id` nullable + CHECK;
  · `jasa.pemilik_hasil()` — beras/menir/broken/reject kembali, bekatul beralih
    milik; penyosohan mewarisi pemilik dari silonya, dan penjaga penolaknya
    DICABUT bersama ujinya;
  · PK walk-in jasa: penolakan di `create_pk_purchase_dari_timbang` dicabut,
    pesanannya dibuat lewat penolong yang sama dengan gabah;
  · gabah basah jasa WAJIB ke pengering (`tumpukan.tujuan_sah`);
  · saringan stok barang jadi & bekatul; `packaging.py` sengaja TIDAK disaring.

## Irisan KETIGA — lingkarannya tertutup

Sisa per fase (`sisa_jasa`), aturan "selesai" satu kalimat, pengambilan,
layar Jasa (`/jasa`), dan notanya. Dengan ini pesanan jasa bisa ditutup.

DUA bug nyata ditemukan uji irisan ini, dan keduanya tak melempar galat:

  · **`baris_dari_item` tak ada.** Tiga tempat menyusun ulang baris perintah
    dari `OutgoingItem` tanpa `jasa_id` — pemiliknya hidup di PERINTAHNYA. Maka
    `tersedia()` membaca stok PABRIK untuk barang pelanggan, menjawab "tinggal
    0 kg", dan pengambilan yang sah ditolak dengan kalimat yang menyuruh
    operator mencari kesalahan yang tak ada. Di lapangan ia akan muncul sebagai
    truk pelanggan yang sudah dimuat lalu tak bisa dicatat.
  · **`pernah_ada_barang` cuma melihat dua tabel.** Pesanan yang barangnya sudah
    di silo Gudang 2 terbaca "belum pernah menerima barang" — lalu ia bisa
    DIBATALKAN, dan barangnya tertinggal tanpa pemilik yang berjalan: saringan
    stok tetap membuangnya dari stok pabrik, jadi ia hilang dari KEDUA sisi.

Dan satu keputusan yang perlu diingat: **nama pemilik yang diketik bebas di Pos
Timbang kini melahirkan baris `pelanggan`** (`find_or_create_pelanggan`).
Bedanya dengan pemasok palsu yang spek larang: pemasok palsu MENIPU ANGKA (ikut
ke skor pemasok, laporan pembelian, HPP sebagai pembelian yang tak pernah
terjadi); baris pelanggan tidak menipu apa pun — risikonya cuma kembar dengan
baris Kledo yang ejaannya beda, dan itu bisa dibereskan belakangan.
`kledo_contact_id` dibiarkan kosong supaya sinkronisasi mingguan tak menimpanya
dan yang membereskan kembarannya bisa mengenalinya.

## Yang BELUM

**SATU hal, dan ia MILESTONE TERSENDIRI — jangan dicicil:**

**Jasa sosoh BROKEN & MENIR.** Rumus rendemen penyosohan berpenyebut PK
(`polishing.py`: `beras_total / pk_terpakai`); sosoh broken dengan rumus itu
menghasilkan angka yang BENTUKNYA rendemen dan ARTINYA bukan — dan seluruh pagar
kewajaran, kabar ke admin, serta pemeriksaan mustahil-rendemen berdiri di atas
angka itu. **Satu proses sosoh broken yang lolos membuat sebaran rendemen tak
bisa dipakai menilai apa pun lagi, untuk SEMUA proses.**

Dua lubang lainnya: penyosohan tak mencatat APA yang disosoh
(`polishing_silo_usage` cuma bobot), dan broken & menir belum punya rumah
sebagai barang MASUK — `BROKEN_MASUK` ada sebagai jenis timbang tetapi sengaja
tak dipetakan di `PETA_MASUK` (keputusan pemilik 24 September: broken beli-luar
adalah pembelian, bukan antrean giling). Jadi `BROKEN_MASUK` akan bercabang dua
arti menurut ada-tidaknya pemilik — `PETA_MASUK` berubah dari peta jadi peta
bersyarat. Perubahan BENTUK, bukan penambahan baris.

⚠ Dan jangan menambah medan "jenis bahan" penyosohan "sekalian": medan yang tak
pernah berubah membuat orang berikutnya menyangka jalurnya sudah ada.

Di Pos Timbang, membukanya nanti = centang `boleh_jasa` pada `BROKEN_MASUK` di
master — nol baris kode.

**Yang sudah selesai** (irisan 1–3): skema sebelas tabel · penjaga kepemilikan
berkunci basis data · saringan stok · tujuh perbaikan G · tumpukan jasa · rantai
Gudang 2 sampai beras · PK walk-in · gabah basah wajib ke pengering · sisa &
aturan selesai · pengambilan · layar Jasa · nota · borang Pos Timbang untuk
ketiga komoditas.


## Yang mudah salah

- **Spek D4 keliru satu hal**: `timbangan_transaksi.pelanggan_id` ada di
  PRODUKSI, tetapi lahir dari rantai migrasi repo `timbangan`
  (`0027_pelanggan_transaksi`, tabel versi `alembic_version_timbangan`) — BUKAN
  rantai produksi. Basis data uji `tests/pg/` dibangun dari rantai produksi saja,
  jadi tanpa penjaga idempoten di 0064 setiap uji yang menyentuh tiket gagal
  dengan "column does not exist".
- **`find_or_create_supplier` adalah jebakan**: tiket MASUK tanpa `supplier_id`
  dulu melahirkan pemasok dari `pihak_nama`. Cabang jasa WAJIB diperiksa lebih
  dulu, kalau tidak pelanggan jadi baris `suppliers` dan barang yang tak pernah
  dibeli ikut ke skor pemasok, laporan pembelian, dan HPP.
- **Dua `_lot_suppliers()` memakai INNER JOIN** (silo.py & drying.py). Sudah
  dibetulkan jadi `outerjoin`; kalau salah satu dikembalikan, lot berisi gabah
  jasa menampilkan daftar KOSONG — barisnya hilang, bukan angkanya salah.
- **Tumpukan di app ini ALARM, bukan ruang tunggu** ("ada tumpukan = ada
  pembelian berlebih"). Aturan itu untuk gabah DIBELI. Barang jasa yang menunggu
  giliran bukan kesalahan pembelian — kalimatnya berbeda, kartunya tetap ada.
- **Tanda ⚠️ TERCAMPUR tidak dipakai untuk silo sepemilik**: pencampurannya
  dikehendaki pemilik barangnya, dan tanda seru yang sering salah berhenti
  dibaca.
- **Pagar rendemen jasa MENOLAK, dan hanya batas MUSTAHIL.** Ambang yang lebih
  ketat ("di bawah X% mustahil") tak boleh dipasang untuk lot KS/MIX: penyebutnya
  bobot basah dan kadar airnya tak diukur. Dan jangan mengoreksi bobot dengan
  hitungan kadar air — perkiraan yang tampil seperti hasil ukur adalah kesalahan
  paling mahal di seluruh pekerjaan jasa.

## Satu hal untuk DIKETAHUI, bukan dikerjakan

`g1_pk_tumpukan_maks_kg = 80_000` (`app/config.py`) sudah hidup di jalur produksi
harian. Keputusan "tidak ada batasan ton" diucapkan dalam percakapan tentang
jasa; mencabut pagar yang sedang bekerja di jalur lain harus DIMINTA, bukan
disimpulkan. Dan di sana perilakunya memang sudah bukan penolakan — lantai penuh
DIBERITAHU, bukan ditolak.

## 2 Oktober 2026 — "tidak terlihat di stock": menyaring ≠ menyembunyikan

Laporan pemilik, dari lapangan: *"pk yang selesai digiling tidak terlihat di
stock oleh admin dan operator gudang 2. kalau ternyata jasa sampai beras putih
harusnya barang bisa dipindahkan ke gudang 2."*

**Dua klaim, dan keduanya diperiksa dengan REPRODUKSI — bukan dengan membaca
kode.** Basis data `uji_lihat` di localhost, `alembic upgrade head`, lalu rantai
sungguhan: tiket → batch jasa → silo → giling → PK 7 ton.

Hasilnya membalik dugaan pertama:

| Yang diperiksa | Hasil |
|---|---|
| `/stok` dirender admin & operator G2 | **BENAR** — lot jasanya ada, lengkap kode `JAS-` & nama |
| `pk_gudang1()` | **BENAR** — `tersedia=7000 jasa_id=1` |
| picker `/actions/pk-g1-tersedia` | **BENAR** — menawarkan lotnya |
| `minta → setujui → kirim` | **BENAR** — `TRF` & intake G2 membawa `jasa_id` |
| **Beranda petak G1 `stok_pk`** | **0 kg** ← yang dilihat orang |
| **`dashboard._stok_pk` total** | **0 kg** |

Jadi bukan izin, bukan rantai. Yang rusak **angka kepalanya**: saya menyaring
Beranda / baris gudang / papan Direksi jadi milik-pabrik dan **tidak menyebut
titipannya di sebelahnya**. Operator membaca "PK 0 kg" di layar pertama lalu
menyimpulkan tak ada apa-apa untuk dipindahkan — kesimpulan yang masuk akal dari
angka yang salah bentuknya.

**Aturannya ternyata punya dua sisi, dan saya cuma menulis satu:**

    jangan pernah MENGHITUNG barang pelanggan sebagai milik pabrik
    jangan pernah MENGHILANGKANNYA dari layar

Saringan tanpa penyebutan sama berbahayanya dengan penjumlahan. Yang pertama
membuat pabrik menjual barang orang lain; yang kedua membuat pabrik
membiarkannya menunggu di lantai sambil mengira gudangnya kosong. Keduanya tak
melempar galat, dan keduanya baru terbaca di gudang.

### Dua cacat lain yang ikut ketemu

1. **`hitung_stok_silo` tidak menyaring `terpakai`.** Saringan pemiliknya
   dipasang pada dua bagian yang MASUK; bagian ketiga — PK yang terpakai
   penyosohan — tak disaring sama sekali. Satu sosoh barang pelanggan lalu
   mengurangi stok PABRIK silo itu: **−1.000 kg**, negatif, tanpa galat.
   Dibuktikan dengan uji mutasi, bukan disimpulkan.

   Bentuk yang menjaganya: `pabrik + jasa == semua` **sesudah sosohnya
   dijalankan**. Tanpa sosohnya `terpakai` nol dan invarian itu lulus dengan
   sendirinya — uji pertama saya begitu, dan ia tak menangkap apa pun.

2. **`LotPk.pemilik` & `TempatPk.pemilik` dihitung lalu tak pernah digambar.**
   Keduanya ada di dataclass sejak jasa sampai Gudang 2; `stok.html` tak
   menyebutnya sekali pun. Jadi silo penuh barang pelanggan tampak persis
   seperti silo pabrik di layar yang justru dibuka untuk memutuskan. Markup-nya
   milik repo `tampilan` (VERSI 175 → 176).

   ⚠ Penjaga pertama saya menghitung kemunculan `"l.pemilik"` di markup-nya, dan
   ia **LULUS** saat markupnya dimatikan `{% if false %}` — tulisannya tetap ada,
   cuma tak pernah tergambar. Diganti dengan merender `/stok` lewat HTTP untuk
   dua peran. *Penjaga yang polanya kurang lengkap lebih buruk daripada tak ada
   penjaga* — kalimat di CLAUDE.md itu, dan saya melanggarnya sendiri hari ini.

### Pola penyebutannya SATU

Angka pabrik apa adanya, titipannya di sebelahnya dengan kata **"titipan"**:
`angka_gudang` → `g1/g2.jasa_pk`; `_stok_pk` → `jasa_total` + `jasa_proses`
(berikut kode `JAS-`, sebab angka tanpa kode tak bisa ditindaklanjuti);
`gabah_hari_ini` → `jasa_kg`/`jasa_batch` (sudah ada sejak irisan pertama — pola
ini TIRUAN darinya, bukan pola kedua).

Dan picker permintaan G2 adalah **kebalikan** dari dua picker penjualan: ia
menawarkan lot jasa, sebab menyosoh barang pelanggan adalah pekerjaan yang
dipesan. Yang dilarang menjualnya, bukan memindahkannya. Labelnya menyebut
`TITIPAN <pemilik>` — operator yang memindahkan tujuh ton tanpa tahu itu titipan
akan memperlakukannya seperti stok pabrik begitu barangnya sampai.

Uji: bagian 7 `tests/pg/test_jasa_ketaatan.py` (5 uji; seluruh berkasnya jadi 26).

## 2 Oktober 2026 — halaman Riwayat sosoh, dan dua kelas CSS yang tak pernah ada

Pintu ke-15. Keputusan pemilik: kartu tiap penyosohan SELESAI berikut neraca
bobotnya — berapa persen jadi beras, broken, menir, bekatul, dan **susut
debu/bobot**. Contohnya ia sebut sendiri: bahan 10 ton, keluar 9.900 kg →
susut 1%.

Yang membuatnya pintu sendiri dan bukan blok di Stok Produk: **susut bukan
stok**. Layar stok menyebut apa yang ADA; susut justru yang TIDAK ada — ia cuma
terbaca sebagai selisih antara yang masuk mesin dan yang keluar darinya, dan
selisih itu tak disimpan di satu kolom pun.

Hubungannya dengan jasa: kartunya menyebut pemiliknya. Rendemen barang titipan
tak boleh ikut menilai mesin pabrik bersama lot pabrik — bahan bakunya datang
dari gudang orang lain dan mutunya tak dipilih pabrik.

### Yang dipelajari

- **Penyebutnya `berat_terpakai_kg`, bukan `berat_awal_kg`.** Pemilik menulis
  "termasuk campurannya", dan itu tepat menunjuk PK yang ditambahkan di tengah
  proses (silo yang dipoles boleh diisi lagi, keputusan 12 Sep). Berat awal akan
  membuat susut terbaca jauh lebih besar — pada angka yang dipakai menilai
  mesin dan orang.
- **Satu penyebut untuk semua persen = identitas 100% yang menjaga kartunya
  sendiri.** Baris "Jumlah" bukan hiasan: satu entri hasil salah ketik langsung
  menggeser susut, dan di sanalah ia terbaca tanpa perlu dicurigai lebih dulu.
- **`reject` tak diminta disebut, tetapi tetap dijumlah.** Membuangnya
  memindahkan beratnya ke susut. Jenis samping baru ikut sendiri — daftar
  sisanya dibaca dari `BYPRODUCTS`, tak ditulis tangan; kalau tidak, susut naik
  diam-diam pada hari sebuah jenis baru dipakai.
- **Rumus dipisah jadi MURNI** (`neraca_sosoh`, `rendemen`) supaya kasus
  tepinya bisa diuji atas angka telanjang. Kasus tepinya justru yang berbahaya:
  bahan nol dan susut negatif dua-duanya berarti salah catat dan dua-duanya
  tak melempar galat.
- **`GRADES` memuat `beras_b`, `stok.GRADES_BERAS` sengaja tidak.** Keduanya
  bukan karena salah satunya lupa — yang kedua memisahkan blok di Stok Produk.
  Menukarnya menggeser penyebut rendemen seluruh pabrik tanpa satu pun galat.
- **`_jam` dinaikkan jadi `lama_kata`.** Berkas `berjalan.py` sudah memuat dua
  pemformat yang hampir sama; yang ketiga di modul lain untuk kalimat yang sama
  akan berbeda kata-katanya begitu salah satu disentuh.

### Dua cacat lama yang ikut ketemu

1. **`pil--aktif` dan `btn--halus` TAK PERNAH ADA di `app.css`.** Keduanya saya
   karang sehari sebelumnya di layar Jasa. Kelas CSS yang tak dikenal tidak
   melempar apa-apa — ia cuma tak menggambar: pil saringan yang aktif tak
   bertanda sama sekali. Yang benar `pil--on` dan `btn--kecil`. ⚠ Cari dulu
   nama kelasnya di `app.css` sebelum memakainya; penjaga mana pun tak akan
   menangkap ini, sebab ia bukan galat.
2. **`dashboard._kode_jasa` mengulang `jasa.nama_pemilik_banyak`** — saya tulis
   sehari sebelumnya juga, berarti hal yang sama persis. Dua penyusun
   "JAS-… Nama" akan menulis namanya dengan dua cara begitu salah satunya
   disentuh, dan yang membacanya mengira itu dua pesanan. Dihapus.

### Uji

`tests/test_neraca_sosoh.py` (10 uji, rumus murni atas angka telanjang) dan
`tests/pg/test_riwayat_sosoh.py` (11 uji: tiga peran yang boleh, satu yang
ditolak DI RUTENYA, kelima persen dirender sungguhan lewat HTTP, kursor, dan
beban kueri). Empat mutasi dibuktikan menggigit — termasuk N+1 yang
dikembalikan (6 → 11 kueri).

⚠ Beban kuerinya dijaga sebagai PERBANDINGAN satu-kartu vs enam-kartu, bukan
langit-langit: langit-langit masih bisa dilewati N+1 yang kebetulan kecil.

## 2 Oktober 2026 (lanjutan) — sub-menu Antrian tunggu, dan jebakan CSS yang berulang

Permintaan pemilik di tengah pekerjaan Riwayat sosoh: *"antrian tunggu bisa
banyak sekali"* → *"bisa tidak antrian tunggu jika di klik muncul dropdown sub
menu?"* → *"sub menu pertama bahan baku, kedua tunggu packing. tunggu
dipindah."*

Infrastrukturnya SUDAH ADA sebagian: `Baris.kelompok` dan `/aksi` sudah
memecah tiga blok di dalam halaman (menumpuk di lantai / tiket belum dicatat /
bisa dikerjakan sekarang). Yang belum pengelompokan untuk sub-menu laci —
dan `kelompok` yang sudah ada tidak bisa dipakai apa adanya: `kelompok=
"tumpukan"` berarti dua hal berbeda di dua gudang. Dipetakan ulang lewat
`aksi` (apa yang DITUNGGU kartu itu), dengan `kelompok` sebagai kaki kedua
untuk kartu DIAM.

Tiga nama `aksi` salah tulis saat peta pertama ditulis (`pk_luar_masuk` yang
benar `catat_pk_luar`, `minta_pk_g1`/`setujui_permintaan_pk` yang benar
`acc_permintaan_pk`) — dan tak satu pun melempar galat, kartunya cuma pindah
diam-diam ke grup "Lainnya". Ketemu lewat perbandingan otomatis terhadap
`aksi=` yang sungguh ada di `berjalan.py`, bukan lewat gudang.

### Jebakan CSS yang sama, dua hari berturut-turut

Sehari sebelumnya (layar Jasa) saya mengarang DUA kelas: `pil--aktif`,
`btn--halus`. Hari ini saat menulis Riwayat sosoh, memeriksa ulang layar Jasa
menemukan EMPAT LAGI: `kartu__judul`, `lencana--netral`, `redup`, `blok`. Dan
satu cacat yang lebih serius — tombol "Tutup pesanan" memakai `data-post`
tanpa `data-kirim`, sementara `aksi.js` mengikat `closest("[data-kirim]")`:
tombolnya **mati total**, tanpa galat, tanpa kabar, sejak dibuat.

Pelajarannya bukan "hati-hati lagi" — itu sudah dicoba dan gagal dua kali.
Yang dipasang penjaga STRUKTURAL: `test_tak_ada_kelas_css_karangan_di_templat_
app_ini` (setiap `class="…"` murni wajib ada di `app.css`) dan
`test_tombol_kirim_di_templat_app_ini_memakai_data_kirim` (setiap
`<button data-post>` wajib `data-kirim`). Keduanya BERSIH saat ditulis atas
templat lama — nol gangguan — yang membuktikan keduanya menangkap sesuatu yang
nyata, bukan menyaring gaya penulisan.

Dan satu bukti kecil yang penting: cabang `boleh_tutup` pada kartu Jasa tak
pernah terlewati oleh satu pun percobaan basis data (pesanan baru selalu
belum boleh ditutup), jadi galat Jinja di dalamnya baru akan muncul di gudang
pada pesanan PERTAMA yang memang sudah selesai. Diuji dengan merender
template-nya langsung atas kartu palsu yang `boleh_tutup=True`.

Uji: `tests/test_grup_antrean.py` (21 uji: pemetaan murni, Σ grup == panjang
antrean, sub-menu & pil dirender sungguhan, dua penjaga umum di atas).

## 2 Oktober 2026 (lanjutan) — "lot paling atas harusnya jasa. kenapa tidak terdeteksi?"

Laporan pemilik, langsung dari layar Stok sungguhan (tangkapan layar): lot PK
LOT-20261002-01 tak bertanda "Titipan", padahal seharusnya titipan pelanggan.
Supplier-nya tertulis "MARNOOO" — nama yang jelas diketik, bukan dipilih dari
master.

**Diperiksa dengan reproduksi, bukan menebak.** Dibuktikan dalam tiga lapis:

1. Pure-function: `_pasang_pihak(trx, "MASUK", None, jasa=True)` →
   `supplier_id=None, pelanggan_id=None` — KEDUANYA kosong.
2. Lewat `simpan_timbang_pertama` sungguhan dengan `pelanggan_id=None,
   pihak_nama="Marnooo", jasa=True`: tersimpan tanpa satu pun penolakan.
3. Lewat `create_purchase_batch_dari_timbang` atas tiket itu, SEBELUM
   perbaikan: `adalah_jasa()` menjawab False, `find_or_create_supplier`
   membuat "Marnooo" sebagai pemasok sungguhan.

**Akarnya:** borang jasa Pos Timbang punya pintu ketik-bebas untuk pelanggan
baru yang belum sampai ke cermin Kledo mingguan — dan itu SAH, bukan bug (spek
D sendiri mewajibkannya: "cermin Kledo disegarkan mingguan, jadi pelanggan
baru memang bisa belum ada"). Tetapi `adalah_jasa()` di produksi hanya membaca
`pelanggan_id IS NOT NULL` — satu-satunya penanda yang tersedia sampai hari
ini — dan nama yang diketik bebas tidak mengisi kolom itu (id-nya baru lahir
di PRODUKSI, lewat `find_or_create_pelanggan`, bukan di Pos Timbang). Baris
tiket "jasa-pelanggan-baru" dan "pembelian-pemasok-baru" jadi **identik
bentuknya** — tak ada satu kolom pun yang membedakan keduanya.

Yang menarik: `pesanan_jasa_dari_tiket()` di produksi SUDAH ditulis untuk
menangani `pelanggan_id is None` dengan fallback ke `pihak_nama` — kode itu
sendiri "tahu" skenario ini mungkin terjadi. Tapi gerbang masuknya
(`adalah_jasa()`) tak pernah diperbarui untuk mengizinkannya lewat. Fallback
yang ditulis itu jadi **kode mati**: tak pernah tercapai, karena gerbangnya
menolak lebih dulu.

### Perbaikan: penanda yang TERSIMPAN, bukan DITURUNKAN

Kolom baru `timbangan_transaksi.jasa` (boolean), diisi SEKALI saat petugas
menekan "Barang masuk jasa" — fakta yang ia tahu pasti pada detik itu, lepas
dari apakah pelanggannya sudah terdaftar. Migrasi kembar: `0041_tanda_jasa`
(repo `timbangan`, pemilik kolomnya) dan `0066_tanda_jasa_tiket` (repo
`produksi`, idempoten — pola yang sama persis dengan `pelanggan_id` di 0064).
Backfill tiket LAMA: `jasa = pelanggan_id IS NOT NULL OR jasa_id IS NOT NULL`
— satu-satunya kebenaran yang tersedia untuk riwayat; tiket jasa lama yang
pelanggannya diketik bebas TETAP salah tanda (tak bisa ditebak lagi dari data
yang sudah terlanjur identik).

`adalah_jasa()` kini: `t.jasa OR pelanggan_id is not None OR jasa_id is not
None` — kaki kedua dipertahankan untuk tiket lama / jalur baca yang belum
memilih kolom baru.

**Cacat kembar, ditemukan sambil memperbaiki yang pertama:** `nama_pihak()`
memeriksa `nama_pelanggan`/`pelanggan_id` SENDIRI, terpisah dari
`adalah_jasa()`. Jadi walau `adalah_jasa()` sudah benar, kartu antrean untuk
pelanggan-baru-ketik-bebas tetap jatuh ke cabang pemasok dan menampilkan nama
telanjang **tanpa tanda "JASA"** — operator yang menerimanya tak diberi tahu
sama sekali bahwa barang ini titipan. Dibetulkan: `nama_pihak()` kini memeriksa
`adalah_jasa(t)`, bukan menyusun syaratnya sendiri.

### Pelajaran metodologis — uji yang membuktikan separuh cerita

`tests/timbangan/test_jasa_masuk.py::test_pemilik_boleh_diketik_bebas` SUDAH
ADA sebelum cacat ini ditemukan. Ia membuktikan `(supplier_id, pelanggan_id)
== (None, None)` sebagai perilaku yang **benar** untuk pintu ketik-bebas — dan
itu memang benar, dari sudut pandang Pos Timbang sendiri. Yang tak pernah
diperiksanya: apakah jejak dua-NULL itu masih bisa dibaca BENAR oleh pembaca
lain — produksi, basis data yang sama, kontrak lintas repo yang tak tertulis
di tipe mana pun. **Menguji bahwa sebuah pintu bekerja tidak sama dengan
menguji bahwa akibatnya di seberang pintu itu benar.**

Dan bagian 1–7 `test_jasa_ketaatan.py` di produksi (26 uji) punya lubang yang
sama persis dari sisi satunya: SELURUHNYA memanggil `_tiket(pelanggan_id=pid)`
dengan `pid` yang sudah dibuat lebih dulu lewat `_pelanggan()` — bentuk yang
TAK PERNAH bermasalah. Tak satu pun mencoba bentuk "pelanggan belum ada",
padahal itu bentuk yang justru spek sebut eksplisit sebagai harus didukung.

### Uji

- `tests/test_adalah_jasa.py` (produksi, baru, 5 uji — murni dict, tanpa basis
  data): ketiga bentuk tiket (lama/baru/biasa) berdampingan.
- Bagian 8 `tests/pg/test_jasa_ketaatan.py` (3 uji, lewat jalur sungguhan:
  gabah DAN PK luar, berikut kartu antreannya).
- `tests/timbangan/test_jasa_masuk.py` bagian 7 (2 uji baru + `test_pemilik_
  boleh_diketik_bebas` diperkuat) dan `tests/timbangan/test_web.py` (1 uji
  HTTP baru, reproduksi langsung "Marnooo" lewat borang sungguhan).
- Migrasi 0066/0041 diuji naik-turun-naik di Postgres sungguhan, termasuk
  backfill atas baris yang sengaja disisipkan menyerupai tiket jasa lama.
- Uji mutasi: definisi lama `adalah_jasa()` dikembalikan sebentar — LIMA uji
  di tiga berkas menangkapnya serentak.

Penjaga skema `tests/timbangan/test_skema.py` (yang glob-nya dilebarkan 1
Oktober, catatan di atas) menangkap migrasi 0041 belum didaftarkan pada
percobaan pertama — bekerja persis seperti yang dirancang.
