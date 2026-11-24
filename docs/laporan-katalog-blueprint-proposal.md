# Proposal compiler lokal: katalog Laporan periode

Basis `d2d036d78f299373bfbd23d6e4512293f515d944`; worktree terpisah dari
root, QC dan Jasa. Hanya file baru helper, adapter wrapper, tests dan handoff.
Tidak ada wiring/handler, DB/models import, runtime guard, atau perubahan vendor.

## Kontrak yang sudah dibuktikan dari source

Katalog `/laporan` terdiri 13 label TAHAP, berperiode=True dan uang=False.
`boleh_lihat` native adalah `(not lap.uang) or can_see_financials(user)`.
Karena seluruh entri saat ini bukan uang, metadata dapat berisi boleh=True
setelah kontrak source ini cocok. Ini bukan pemberian akses: `butuh_akun`,
handler, resolver descriptor, tenant dan GET guard tetap milik produk/root.
Jika kontrak constructor, uang atau predicate berubah, helper berhenti saat
build dengan ValueError untuk review owner, bukan menebak role baru.

Helper `scripts/kerangka_laporan_katalog.py` memakai AST saja: TAHAP dibaca
key dan elemen tuple pertama (label); referensi model selanjutnya tidak pernah
dievaluasi. PERIODE dibaca literal. Tidak memanggil _daftar(), tidak mengimpor
app.services/models/database/settings, dan tidak memerlukan record atau akun.

## Cara integrasi compiler root

- Import helper melalui importlib (atau modul scripts namespace).
- `public = metadata(ROOT)` menyediakan daftar/metadata label periode native.
- Root menyiapkan `native_navigation` dari `laporan_navigasi.siapkan` / pilihan
  native pada dokumen yang sah. Jangan membuat account untuk build, menebak
  mapping role, atau memakai pilihan tenant lain. Jika blueprint generic perlu
  beberapa varian layout, root memilih snapshot public yang memang dihasilkan
  jalur native; helper tidak memutuskan varian mana berizin.
- Snapshot exact memiliki aktif, judul, jenis, detail, panduan, tab, pilihan,
  boleh_alamat. Untuk katalog aktif=laporan, detail=False, pilihan=[]; tab
  berisi hanya kunci/nama/href/boleh/alamat, tanpa hitungan atau identitas.
  Jenis native pada `/laporan` adalah laporan. Runtime menyuplai ulang snapshot
  current; snapshot compiler bukan cache keputusan otorisasi.
- `render_blueprint(env, public=public, native_navigation=snapshot, cap=CAP,
  tampilan_induk=flag_native)` merender block isi **laporan.html asli**, lalu
  memasukkannya dalam adapter `laporan_katalog_blueprint.html` yang menyalin
  tepat wrapper base `.laporan-riwayat` + `_laporan_navigasi` + `.laporan-isi`.
  Body safe berasal render template compiler sendiri, bukan HTML dari request.
- Gunakan loader app dahulu lalu hmu_tampilan dan StrictUndefined. Tidak perlu
  menjalankan base penuh. Jangan menggambar H1, tabel, filter periode atau
  input laporan detail di katalog: native katalog tidak memilikinya.

`aktif=laporan` sengaja tidak menggambar tab riwayat, picker atau tombol Cetak.
Panduan tetap pada posisi toolbar native. Tetapi array tab tetap dibaca
laporan-kontrol.js untuk menu Riwayat/sessionStorage; helper mempertahankan
snapshot persis dan tidak mengosongkan/menambah pilihan itu. Variasi boleh=True/
False diuji sebagai bentuk metadata publik, bukan sebagai role permission test.

Root memasukkan helper/adapter dan `source_pins(ROOT)` ke manifest compiler.
Pins helper adalah minimum source otoritatif, bukan manifest aset lengkap.
Loader root tetap merekam partial `_laporan_periode_gaya`, `_kontrol_halaman`,
`_panduan`, `_laporan_kontrol` dan semua aset yang benar-benar dibaca:
`laporan-riwayat.css`, `laporan-kontrol.css`, `laporan-kontrol.js`, serta CSS
inline katalog dari partial. Root sendiri meninjau inlining/CSP, descriptor
GET-only dan binding route/sesi, tanpa mengubah shared compiler pada child.

## Bukti dan batas

17 pure tests PASS: metadata 13 label/periods native tanpa mengevaluasi model,
review-required bila predicate/constructor berubah, render katalog sama native,
wrapper/control positions nyata, tidak ada H1/tabel/form/data/draft, pilihan
native tersalin tanpa role mapping, dan metadata identitas/jumlah ditolak.
Test memakai tiny base agar tidak boot app. Tidak ada PG/browser/listener,
server handler, role runtime, PWA, first-click atau deployment test di sini.

Belum wired berarti belum mengubah perilaku pengguna. Laporan detail/data/PDF
serta tabel Sosoh dinamis tetap HOLD; tidak memakai schema kosong untuk
menyamarkan ketergantungan hasil nyata. QC/Jasa/Transfer tetap tidak disentuh.
