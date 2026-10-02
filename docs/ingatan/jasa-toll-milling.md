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
