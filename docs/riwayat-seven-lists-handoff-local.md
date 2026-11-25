# Handoff adoption lokal tujuh daftar

Product delta tetap exact `dd7b2c583d3b6ff22b162d39cc16683db910709f`, di atas
frozen proposal fed2f105 + root dependency e6c40ad (local cherry 7bd7743).
Commit setelahnya hanya owner-test/harness oracle/guard/docs, bukan gate, izin,
reader, scope, saldo, writer, atau UI produk. Root belum memasang first-click
public registry untuk keluarga ini; document-before-heavy-read sudah diadopsi
secara lokal pada handler keluarga. Tidak menyebut semua halaman selesai.

## Bukti yang dipertahankan

- dd7b2c5: 3 server-role PASS untuk Admin, Operator G1 dan Operator G2 pada
  tujuh route. Guard, header, document yang tidak membaca heavy process reader,
  native GET X-Pindah decline dan seluruh fingerprint tabel tetap. Browser ASGI
  gagal masuk shell; hasil itu dipertahankan, tidak disembunyikan.
- 8c314882 protocol proof PASS: bridge Playwright route interception tidak
  meneruskan Sec-Fetch navigation metadata. Gate benar menolak shell di sana.
  Browser HTTP native membawa mode navigate + dest document sehingga shell
  tampil; native GET X-Pindah:1/explicit:0 ditolak dari shell dan membaca data
  asli. Tidak melonggarkan auth/gate atau memalsukan header agar uji lulus.
- 2212cbf focused02: Admin 390 PASS semua tujuh route, phone field labels,
  tiga process native caption/value persis, empat QC header saat kosong,
  keyboard guide, read-failure/GET retry, keluar saat GET pending tanpa respons
  menimpa tujuan, zeroPOST dan fingerprint seluruh tabel tetap. Case berikut
  gagal rebind listener fixture; bukan bukti regresi produk.
- ce2db59 shared lifecycle: Operator G1/390 dan G2/390 masing-masing PASS tujuh
  keputusan scope, parity, GET retry, pending navigation dan fingerprint.
  Admin 1280 melewati tujuh route/header/parity serta GET retry, lalu timeout
  BrowserChecks.drain_finite pada akhir navigasi pending. URL Barang Masuk dan
  visibility tujuan telah lulus sebelum timeout. Fingerprint tetap. Dua case
  Operator 1280 belum dijalankan. Tidak menandai batch PASS.

Semua run memiliki source/harness pins tetap, SCRAM fixture sekali pakai,
PostgreSQL stopped/deleted, workers exit 0 tanpa forced stop dan seluruh port
HTTP fixture tertutup. Receipt authoritative ada di folder output yang dicatat
checkpoint eksternal; tidak menghapus bukti gagal atau mengulang Admin 390/
protocol yang sudah lulus. Tidak ada tindakan produksi, remote, CI resmi/deploy.

## Pembatasan CI: empat file proof bukan dependency native di CI biasa

Keempat file berkaitan owner-native:

1. `test_riwayat_seven_list_adoption.py`: **campuran**; tiga server-role cases
   wajib tetap aktif. Hanya enam browser cases memakai skipif environment
   OWNER_BROWSER chromium/webkit + DETAIL_OUT + PWA_GUARD.
2. `test_riwayat_gate_protocol.py`: satu owner-native protocol proof, guard sama.
3. `test_riwayat_remaining_native_batch.py`: satu owner-native batch/proof lima
   subcase, guard sama.
4. `riwayat_seven_native_http.py`: support helper, bukan test collection;
   memeriksa owner environment sebelum import native_runtime/transport dan
   browser runtime. External approved harness tetap di output, tidak dibundel
   ke source produk atau dijadikan dependency CI mandatory.

Import external native_runtime/native_transport/browser_checks hanya di fungsi
owner yang sudah diguard. Import Playwright opsional juga dipindah ke fungsi.
Guard bukan skip terhadap kegagalan dalam fixture sah: approved runner memasok
semua marker sehingga seluruh owner assertion tetap berjalan.

Untuk set 13 mandatory CI yang dimiliki root, jangan mengganti daftar root
dengan owner proof atau menganggap hybrid server-role file sepenuhnya opsional.
Child menyediakan `test_riwayat_seven_list_native_pure.py` (61 PASS) dan tiga
server-role cases wajib di file hybrid. Pure guard regression memastikan ketiga
server cases tidak diberi skip. Pemilihan 13 file lengkap/official CI tetap root;
child tidak menjalankan atau mengklaim seluruh set itu lulus.

Tanpa owner environment: delapan owner nodes skipped secara eksplisit, tiga
server cases deselected hanya oleh selector validasi portability, bukan skip
mark. Tidak memulai PG untuk pemeriksaan portability ini.

## Diagnosis read-only dan satu proposal target berikut

BrowserChecks.drain_finite memelihara set same-origin request non-eventsource
(kecuali /api/aliran dan /sw.js), menghapus hanya saat requestfinished atau
requestfailed. Saved native proxy calls pada shared-run setelah cleanup semuanya
outcome=response, termasuk GET riwayat yang ditinggalkan dan data Barang Masuk
200. Tetapi path/resource_type/request.failure dan event-history dari **set
browser yang masih pending tepat saat timeout** tidak tersimpan. Tidak cukup
untuk menyatakan bug observer, request produk macet, atau masalah jaringan.

Satu target diagnosis yang diusulkan untuk exact root gabungan nanti: Admin
1280, tahap navigasi keluar saat native GET pending saja. Sebelum teardown pada
timeout lama yang sama, rekam daftar pending browser path/resource_type/method,
failure category dan event requestfinished/requestfailed yang telah diamati;
rekam proxy outcome saat itu serta boolean tujuan aktif/old shell absent.
Tanpa query credentials/tokens/HTML, tanpa menambah delay atau menaikkan timeout.
Jangan ulang tiga case 390/protocol/parity yang sudah lulus hanya untuk ini.
Dua Operator 1280 dan sisa verifikasi gabungan direkonsiliasi root setelah
registry/Giling diintegrasikan; child tidak memulai run tambahan.
