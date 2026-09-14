# Peta batas modul — keadaan HARI INI (13 September 2026)

Dokumen ini apa adanya, bukan cita-cita: untuk setiap tabel di basis data,
**siapa yang menulis dan siapa yang membaca**, disisir dari kode ketujuh
repo (`produksi`, `core`, `kantor`, `timbangan`, `meja`, `gudang2`,
`website`) — bukan dari ingatan. Tabel yang punya lebih dari satu penulis
ditandai **⚠ multi-penulis**; itulah daftar pekerjaan Tahap 4. Catatan
keputusannya: `docs/ingatan/rancang-ulang-2026.md`.

Cara membaca: *penulis* = INSERT/UPDATE/DELETE dari kode aplikasi (skrip dan
migrasi data disebut terpisah); *pembaca* = SELECT. Nomor baris merujuk
commit hari ini dan akan basi — nama berkasnya yang penting.

Ringkasan angka: **76 tabel data + 4 tabel versi Alembic** (`uji_gudang2`,
skema dari empat chain). Seluruh 76 tabel dibuat oleh chain **produksi**
(45 migrasi); chain core (1) hanya di-stamp; chain kantor (4) mengadopsi
lalu ALTER; chain timbangan (15) mewarisi 0022–0026 lalu membuat
`timbangan_penimbangan` & `timbangan_nomor` sendiri. `meja`, `gudang2`,
`website` **tidak menyentuh basis data sama sekali** (§5).

---

## 1. Tabel master bersama (paket `hmu_core`)

| Tabel | Penulis | Pembaca | Catatan |
|---|---|---|---|
| `users` | ⚠ **produksi**: `app/services/user_admin.py` (daftar orang, status, kontak), `app/web/pengguna.py` (status ikut nonaktif akun), `app/web/pengaturan.py` & `app/web/meja_api.py` (nama), `app/services/seed.py` + `app/seed.py` (admin awal), `app/services/data_uji.py`, 4 skrip uji · **kantor**: `app/services/akun.py` (aktivasi Telegram: `telegram_user_id`, `status`, `nama`), `app/kantor/rbac_onboard.py` (INSERT orang baru, UPDATE nama) | produksi (api, security, nav, audit, berjalan, `input_by` di semua proses); kantor (`bots/common.authenticate` tiap pesan); timbangan (`routes/auth.py`, `security.py` — hanya `status` saat login) | Satu orang satu baris; `role` dibaca semua, ditulis produksi & seed saja (kantor sengaja tak menimpa). `users.status` = saklar yang diperiksa ketiga app (X-11), tetapi rute penyetelnya sempat 500 (R-P-01) |
| `suppliers` | ⚠ **produksi**: `gudang1/services/purchase.py:55-80` `find_or_create_supplier`, `app/services/data_uji.py` (RAW INSERT), 4 skrip uji · **kantor**: `app/kantor/kledo_kontak.py` (INSERT kontak Kledo baru, UPDATE `kledo_contact_id`/nama/telepon/alamat — mingguan, tak pernah DELETE) · **timbangan**: DDL saja, migrasi `0022:45` ADD COLUMN `kledo_contact_id` (melanggar kontrak `timbangan/app/models.py:17-18`) | produksi (report 23 ref, berjalan, stok, analytics, dashboard, milling, silo, drying, rekonsiliasi, gudang2, api); timbangan (`daftar_supplier`, `daftar_pihak`, join tara & laporan); kantor (sinkron) | Tiga penulis — X-20; indeks unik parsial `uq_suppliers_nama_hidup` (0045). `timbangan_supplier_profil.supplier_id` & `timbangan_skor_supplier.supplier_id` WAJIB ISI → hapus supplier merusak timbangan; X-01 lahir dari CASCADE lewat FK masuk ini |
| `pelanggan` | ⚠ **kantor**: `kledo_kontak.py` (sinkron Kledo tipe 3) · **produksi**: hanya `scripts/uji_mode_uji.py` | timbangan (`daftar_pihak`, laporan — pelanggan pengiriman/retur); produksi tidak membacanya (hanya impor model) | Dibuat produksi 0029 + core 0001. Penulis nyatanya kantor, pembaca nyatanya timbangan — tak satu pun "pemiliknya" di atas kertas |
| `warehouses` | ⚠ **produksi**: `app/services/seed.py:48` (startup) dan `app/seed.py:26-42` (CLI) — dua penyemai beda isi (`kapasitas_tumpuk_pk_ton` hanya diisi yang CLI) | produksi (silo, drying, gudang2, user_admin, api, peran, meja_api, gudang2_api); timbangan tidak; kantor tidak | Dilindungi Mode Uji |
| `silos` | ⚠ **produksi**: status oleh `gudang1/services/silo.py:387,611`, `milling.py:393`, `undo.py:367,427,471`; INSERT oleh `web/pengaturan.py:318` DAN `web/meja_api.py:802` (dua jalur UI, validasi disalin); seed ×2 | produksi (api 30 ref, gudang2 service/polishing, berjalan, dashboard, transfer, layar, peta_jenis) | Silo Gudang 2 = tabel yang sama dengan silo Gudang 1, dibedakan `warehouse_id` — bagian jahitan §3 |
| `dryers` | ⚠ **produksi**: `web/pengaturan.py:286,345`, `web/meja_api.py:774,823`, seed ×2, **migrasi data** `0003_dryers.py:33-41` | produksi (`drying.py` baca saja: `dryers_g1`, `pilih_dryer`; tumpukan, analytics, report, setelan, api) | Kapasitas "Pengering 1" berbeda antar penyemai: 30.000 (0003, `services/seed.py`) vs 35.000 (`app/seed.py:59`) — **perlu dicek**, angka ini menentukan penolakan muatan |

## 2. Tabel per repo

### 2.1 Produksi — Gudang 1 (selepan)

| Tabel | Penulis | Pembaca | Catatan |
|---|---|---|---|
| `purchase_batches` | ⚠ ≥9 modul produksi: `purchase.py` (I manual & dari tiket, D undo 15 mnt), `timbang_link.py:146-220` (RAW UPDATE sinkron bobot), `drying.py`, `silo.py`, `tumpukan.py`, `milling.py` (status), `verification.py` (`flag_unverified`), `undo.py` (U/D), `mode_uji.py` (RAW DELETE massal) | produksi (report 38 ref, analytics, berjalan, stok, dashboard, pemantau, costing, rekonsiliasi, api, meja_api, codegen); **timbangan** baca-saja `tautan_produksi.py:29-30` (tolak void/ubah bila tertaut) | Jembatan ke timbang: `timbangan_transaksi_id` UNIQUE per tabel (X-13: satu tiket bisa jadi GB dan PKB) |
| `purchase_batch_verifications` | `verification.py:76-83` (upsert harga), `undo.py:274` (D) | analytics, report, costing, milling, rekonsiliasi | rupiah — lihat §4.6 |
| `drying_lots` | `drying.py` (I, U pendinginan/target/selesai), `undo.py` (U/D), `data_uji._mundurkan` (RAW U — kemungkinan kode mati) | api 17 ref, berjalan, report, pemantau, dashboard, silo, jeda, codegen, costing | |
| `drying_lot_batches` | `drying.py:573,776` (I), `undo.py` (D) | milling 15 ref, silo, stok, report, pemantau, costing, analytics | jembatan; tak pernah UPDATE |
| `drying_moisture_logs` | `drying.py:679` (I), `undo.py` (D) | drying | |
| `drying_cooling_logs` | `drying.py` (I), `undo.py` (D) | drying | |
| `silo_storage` | `silo.py` (I dari pengeringan/langsung, U kosong), `milling.py:388` (U kosong saat giling), `undo.py` (D/U) | milling, pemantau, drying, report, berjalan, dashboard, api | Gudang 1 saja; Gudang 2 memakai `pk_gudang2_intakes` — §3 |
| `silo_moving_logs` | `silo.py` (I mulai/selesai), `undo.py` (D) | silo.py sendiri | tak dibaca laporan mana pun |
| `milling_process` | `milling.py` (I, U selesai, U berat re-sinkron), `silo.py:421` (`update()` tambah berat, P-K-14), `undo.py` (D/U), `data_uji` (RAW U) | api, report, analytics, berjalan, transfer, pemantau, stok, dashboard, costing, rekonsiliasi, aksi_inventory, outgoing | `berat_gabah_masuk_kg` tiga penulis (disengaja, terdokumentasi) |
| `milling_process_sources` | `milling.py:144,963`, `silo.py:406` (I gabah menyusul), **migrasi data** 0031 | stok, berjalan, undo (cek pemakaian), `scripts/telusur_lot.py` | |
| `milling_progress_logs` | `milling.py` (I), `undo.py` (D) | report, costing, analytics, transfer | |
| `milling_qc_logs` | `milling.py:775` (I), `undo.py` (D) | stok, dashboard, berjalan, report, api, analytics | |
| `milling_process_verifications` | `milling.py:834` (upsert), `undo.py` (D) | analytics, dashboard, transfer, pemantau, costing, berjalan, report, api | rupiah — §4.6 |
| `milling_pk_routing`, `pk_stock_gudang1` | — | — | **dibuang** migrasi 0033; masih tercantum di daftar `drop_table` riwayat. Tidak ada di DB uji |
| `jeda_proses` | `gudang1/services/jeda.py` (I, U `selesai`), `milling.py:291` (U tutup jeda saat giling selesai), *(branch gudang2-api)* `gudang2/polishing.py` (U tutup jeda penyosohan) | jeda, milling, api, berjalan | Satu tabel untuk pengeringan, giling, dan (branch) penyosohan |

### 2.2 Produksi — Gudang 2 (penyosohan) — seluruhnya juga bagian §3

| Tabel | Penulis | Pembaca | Catatan |
|---|---|---|---|
| `pk_purchase_batches` | `gudang2/service.py` (I manual & dari tiket, U `flag_unverified`, U `status_batch`), `timbang_link.py:150,215` (RAW U bobot — loop dua tabel), `undo.py:575` (D) | berjalan 16 ref, api, pemantau, report, meja_api, layar, stok, codegen, rekonsiliasi; **timbangan** baca-saja (`tautan_produksi.py:32`) | Jembatan ke timbang, UNIQUE per tabel |
| `pk_purchase_verifications` | `gudang2/service.py` (I; U lab QC; U harga), `undo.py` (D, U nullify) | pemantau, api, berjalan, rekonsiliasi | satu baris, dua tahap (QC lalu harga) — §4.6 |
| `pk_gudang2_intakes` | `gudang2/service.py:599` `_add_intake` — dipanggil dari PK luar DAN dari `app/services/transfer.py:184` (transfer G1→G2); U `hpp_per_kg` saat harga diverifikasi; `undo.py` (D, U) | berjalan, stok, pemantau, api | Satu penulis, dua pemicu dari dua "gudang" |
| `pk_tumpukan_to_silo` | `gudang2/service.py:754,832` (I) — sampai 12 Sep tak punya pintu di layar (P-K-20); branch `gudang2-api` memberinya aksi operator | codegen, berjalan | tak pernah U/D; **tidak ditangani undo** |
| `polishing_process` | `gudang2/polishing.py` (I, U selesai) | report, berjalan, finished_goods, api, codegen, gudang2 service, layar, aksi_inventory, pemantau | tidak ditangani undo |
| `polishing_silo_usage` | `gudang2/polishing.py` (I snapshot awal; U akhir/terpakai), *(branch)* `_catat_masuk_selama_proses` (U `berat_masuk_kg`) | gudang2 service (`hitung_stok_silo`), berjalan, finished_goods | rumus stok silo G2 — P-K-11 |
| `polishing_output_logs` | `gudang2/polishing.py:170` (I kumulatif) | report, finished_goods | tak pernah diubah |
| `pk_rejections` | **tak ada penulis** | codegen (`next_rejection_code`, tak pernah dipakai) | **tabel mati**, calon dibuang seperti 0033 |

### 2.3 Produksi — persediaan (kemasan, barang jadi, keluar)

| Tabel | Penulis | Pembaca | Catatan |
|---|---|---|---|
| `rice_quality_standards`, `brands`, `packaging_materials`, `package_sizes` | `app/services/seed.py` (I) ; migrasi data 0043 mengisi NULL | packaging, finished_goods, aksi_inventory | master acuan; dipertahankan Mode Uji |
| `product_skus` | `inventory/packaging.py:117` `find_or_create_sku` | finished_goods 8 ref, aksi_inventory | cari-lalu-buat **tanpa indeks unik** — kerentanan yang sudah ditutup untuk `suppliers` (0045); **perlu dicek** |
| `packaging_purchases` | `packaging.py:234` (I) — dipicu Meja lewat `/api/actions/beli-kemasan` (M-03) | packaging (`hitung_stok_kemasan`), codegen | harga per lembar di dalamnya — §4.6 |
| `packaging_losses` | **tak ada penulis** | `packaging.py:147` (pengurang stok karung) | rumus stok memperhitungkan kehilangan yang tak pernah bisa dicatat — **fitur belum selesai** |
| `finished_goods_stock` | `finished_goods.py:150` (I saat packing) | finished_goods, packaging, report, aksi_inventory, *(branch)* gudang2_api | append-only; pengurang lewat `outgoing_items`; tidak ditangani undo |
| `byproduct_stock` | `finished_goods.py:201` (I bekatul curah) | finished_goods | |
| `byproduct_prices` | `finished_goods.py:54` (I riwayat harga) | finished_goods | rupiah — §4.6 |
| `outgoing_records` | `inventory/outgoing.py:41` (I) | report, codegen | |
| `outgoing_items` | `outgoing.py:88,122,162` (I: barang jadi / PK langsung / curah) | finished_goods, milling (sisa PK), transfer, report | pengurang stok untuk 4 modul; tak pernah U/D |
| `internal_transfers` | `app/services/transfer.py:161` (I), `undo.py:490` (D) | milling 9 ref (sisa PK), stok, berjalan, gudang2 service, codegen | **jahitan G1→G2** — §3 |

### 2.4 Produksi — akun, jejak, sistem

| Tabel | Penulis | Pembaca | Catatan |
|---|---|---|---|
| `peristiwa` | `app/services/peristiwa.py:catat` — SATU penulis (dipanggil `purchase.create_purchase_batch_dari_timbang` dan `undo._undo_purchase`); TAMBAH-SAJA, trigger menolak UPDATE/DELETE (migrasi 0047) | `bangun_ulang` (proyeksi), `purchase._batch_dari_kunci` | Buku besar Tahap 3. Jenis hari ini: `gabah_masuk`, `pk_luar_masuk`, `pk_masuk_g2`, `pk_dipindah_g1g2`, `pk_tumpukan_ke_silo`, masing-masing dengan `_dibatalkan` |
| `proyeksi_pk_luar_masuk` | penangan di `services/peristiwa.py` (kembaran gabah; migrasi 0048) | belum ada layar — cerminnya `pk_purchase_batches` | Turunan murni; indeks unik parsial per tiket hidup |
| `proyeksi_pk_masuk_g2` | penangan di `services/peristiwa.py` (migrasi 0049); sumbernya `_add_intake` (PK luar & transfer G1) | belum ada layar — cerminnya `pk_gudang2_intakes` | Turunan murni; unik parsial per batch / per transfer yang hidup; `hpp_per_kg` potret saat masuk |
| `proyeksi_transfer_pk` | penangan di `services/peristiwa.py` (migrasi 0050); sumbernya `services/transfer.py` | belum ada layar — cerminnya `internal_transfers` (status `dibatalkan`, tak dihapus) | Turunan murni; `intake_peristiwa_id` menunjuk pasangan `pk_masuk_g2` |
| `proyeksi_pindah_tumpukan_silo` | penangan di `services/peristiwa.py` (migrasi 0051); sumbernya `gudang2.service._catat_pindah` | belum ada layar — cerminnya `pk_tumpukan_to_silo` | Turunan murni; `ke_proses` bila dituang ke silo yang dipoles |
| `proyeksi_gabah_masuk` | penangan di `services/peristiwa.py` (I saat catat, U status saat dibatalkan; dikosongkan+diisi ulang oleh `bangun_ulang`) | belum ada layar — cerminnya `purchase_batches` yang dibaca layar (cermin bertanda `dibatalkan_pada`, saringan sesi `app/models/cermin.py`) | Turunan murni; indeks unik parsial: satu tiket satu pencatatan hidup |
| `produksi_akun` | ⚠ empat jalur produksi: `web/pengguna.py` (buat/reset/status/mode), `web/meja_api.py` (implementasi paralel operasi yang sama untuk Meja), `web/auth.py` (login, `token_version`, ganti sandi), `web/seed_akun.py`; `data_uji`; 4 skrip uji | security 11 ref, pengaturan, mode_uji, deps; **meja & gudang2** lewat `/internal/meja/masuk|saya` | Identitas kedua di samping `users` (dan ketiga: `timbangan_akun`) — X-11 |
| `activity_logs` | `app/services/activity_log.py:33` — satu-satunya INSERT (dipanggil ±40 tempat, tak commit sendiri); `undo.py:930` (U `dibatalkan_pada/oleh`, bukan DELETE — P-K-21) | audit (List audit), undo (`_log_terakhir`), api (`/keadaan` cap versi) | append-only; dipertahankan Mode Uji |
| `notifications` | `app/services/notification.py` (I), `drying.py:1112` (I telat; `update()` selesai), `verification.py:98` (`update()` selesai) | `drying.py:1103` (cek kembar) — **tak ada pembaca lain di repo mana pun** | ditulis & ditutup, **tak pernah ditampilkan** — sisa era bot |
| `setelan_pabrik` | `app/services/setelan.py:34` (I/U) — satu penulis; dipicu Pengaturan produksi DAN `/internal/meja/pengaturan/*` | setelan → drying (target), jeda (sebab), layar mutu | berkunci `kunci`; dipertahankan Mode Uji |
| `kode_urut` | `app/services/codegen.py:66` (`INSERT … ON CONFLICT DO UPDATE … RETURNING`, atomik — P-K-01), **migrasi data** 0038 | codegen (fungsi yang sama) | dihapus Mode Uji supaya nomor mulai 1 |
| `kantor_config`, `kantor_llm_usage` | ⚠ **dua guard atas satu tabel**: produksi `app/ai/guard.py` (kill-switch, spend-cap, catat per panggilan LLM agen pabrik) dan kantor `app/ai/guard.py` + `app/kantor/jadwal.py` (upsert `jadwal:*`) | kedua guard; kantor `rbac.py` (`rbac_enforce`), `kendali.py` | K-10: batas & kill-switch dibagi dua aplikasi; nama `kantor_*` warisan satu-repo |

### 2.5 Kantor (`kantor_*`) — ditulis & dibaca kantor saja

| Tabel | Penulis | Pembaca | Catatan |
|---|---|---|---|
| `kantor_sop_dokumen`, `kantor_sop_chunk` | `app/kantor/knowledge/ingest.py`, `pengetahuan.py` (embedding) | retrieve, pengetahuan | |
| `kantor_aksi_pending` | `app/kantor/persetujuan.py` (I `buat_pending`; U klaim/gagal/dieksekusi/ditolak), `proaktif/persetujuan.py` | persetujuan, bot, proaktif | tak ada DELETE |
| `kantor_audit_log` | `persetujuan.py:353` (I, payload diredaksi) | **tak ada pembaca di kode** | write-only |
| `kantor_chat_riwayat` | `app/kantor/riwayat.py` (I, D prune >40, D `/lupakan`) | riwayat | |
| `kantor_nomor_dokumen` | `dokumen/penomoran.py` (I retry unik, U batal) | penomoran | `batalkan_nomor` tanpa pemanggil |
| `kantor_aturan_email` | `app/kantor/aturan.py` (I sesudah persetujuan) | aturan, proaktif/email_rapi | |
| `kantor_heartbeat` | `app/services/heartbeat.py` (I id=1, U tiap 120 s) | heartbeat (deteksi downtime) | |
| `kantor_role`, `kantor_user_role`, `kantor_grant` | `rbac_seed.py` (role, grant), `rbac.py` (penugasan; nonaktif = UPDATE, tak DELETE) | rbac (gerbang alat), produksi.py (flag financial) | `TABEL_BASELINE` adopsi di `migrations/env.py` tak menyebut ketiganya — **perlu dicek** |
| `kantor_aset`, `kantor_kartu_pemeliharaan` | **tak ada** | **tak ada** | **tabel mati**; kartu servis nyata dari Google Sheet |

### 2.6 Timbangan (`timbangan_*`) — ditulis & dibaca timbangan; satu dibaca produksi

| Tabel | Penulis | Pembaca | Catatan |
|---|---|---|---|
| `timbangan_transaksi` | timbangan `service.py` (I `simpan_timbang_pertama`; U di ±14 tempat; D `:2430`; U NULL petugas saat `hapus_akun`), 4 skrip perbaikan (`ganti_awalan_kode`, `hitung_ulang_nota_kosong`, `perbaiki_jam_wib`, `rapikan_pihak_pengiriman`) · **produksi** hanya `data_uji.py:134` (RAW INSERT tiket uji) & `mode_uji.py:229` (RAW UPDATE NULL FK) — dijaga `jembatan_sungguhan()` | timbangan (semua layar); **produksi** baca-saja `timbang_link.py` (`_SQL_AKTIF`, `FOR UPDATE` = kunci, bukan tulis), `rekonsiliasi.py`, `milling.py:574`, `api.py:86` | **Satu-satunya tabel timbang yang dibaca produksi** — kontrak ARSITEKTUR §3.1. Kolom `purchase_batch_id`/`pk_purchase_batch_id` di tabel ini **tak pernah diisi siapa pun**; arah tautan yang hidup adalah `purchase_batches.timbangan_transaksi_id` |
| `timbangan_penimbangan`, `timbangan_muatan` | service (I/U/D lewat relasi) | relasi `selectin` tiap tiket | |
| `timbangan_akun` | timbangan `service.py`, `routes/master.py`, `routes/auth.py` (I/U/D); **migrasi data produksi** `0026:80` (`UPDATE role='PETUGAS'`) | timbangan security/auth/master; produksi tidak | identitas ketiga — X-11; FK opsional `user_id → users`; login menolak bila `users.status` nonaktif |
| `timbangan_config`, `timbangan_tara_standar`, `timbangan_kendaraan`, `timbangan_pemeriksaan`, `timbangan_cetak`, `timbangan_audit`, `timbangan_nomor` | timbangan service/setelan/routes (+ skrip) | timbangan | `timbangan_audit` append-only; `timbangan_nomor` penghitung atomik (T-01) |
| `timbangan_jenis` | `service.py:171` (I semai saja); skrip uji produksi (RAW INSERT) | timbangan; **produksi** `timbang_link.py:62,89` (JOIN nama komoditas) | **tak ada layar edit** — "aturan di data" hanya bisa lewat SQL |
| `timbangan_foto`, `timbangan_skor_supplier`, `timbangan_supplier_profil` | fungsi penulisnya ada (`simpan_foto`, `simpan_skor`, `profil_supplier`) tetapi **tak punya pemanggil** | `supplier_profil` dibaca `monitoring_supplier`; dua lainnya tidak | **kode mati / tabel yatim** |

## 3. Jahitan Gudang 1 ↔ Gudang 2 — dan temuan yang lahir di sana

Aliran fisiknya satu: PK hasil giling (G1) atau PK beli luar → transfer /
intake → tumpukan atau silo Gudang 2 → penyosohan → beras. Kodenya juga
satu proses (`produksi`). Yang membuatnya terasa dua sistem adalah tabel
yang duduk tepat di jahitan dan ditulis/dibaca dari kedua sisi:

| Tabel di jahitan | Sisi G1 | Sisi G2 | Temuan yang lahir di sini |
|---|---|---|---|
| `internal_transfers` | ditulis `app/services/transfer.py` (hitung sisa PK dari `milling_progress_logs` − `outgoing_items` − transfer sebelumnya) | dibaca `gudang2/service.py` (asal intake), dan `_add_intake` dipanggil langsung dari `transfer.py:184` | **P-K-06**: dua transfer bersamaan → 6 t jadi 12 t di G2, G1 menampilkan 0 (clamp); ditutup FOR UPDATE. Ketelusuran LOT→TRF putus bila ini dianggap jahitan antar-sistem |
| `pk_gudang2_intakes` | dipicu transfer (sumber `transfer_internal`) | ditulis `_add_intake`, dibaca stok silo/tumpukan | **P-K-04**: PK luar masuk dua kali 20/20 → 320 t tercatat dari 160 t; ditutup kunci baris + indeks unik parsial. **P-K-10**: undo intake sesudah dipoles → silo −7.000 kg (masih terbuka) |
| `pk_purchase_batches` | tiket timbang (kontrak timbang, `timbang_link` RAW UPDATE bobot) | ditulis gudang2 service, harga oleh Meja | **X-13**: satu tiket bisa jadi GB (G1) dan PKB (G2) sekaligus |
| `silos` Gudang 2 + `pk_tumpukan_to_silo` | — | stok silo G2 = intake + pindahan − terpakai (`hitung_stok_silo`) | **P-K-11**: silo G2 menerima PK saat dipoles, 12 t vs fisik 7 t (branch `gudang2-api` mengubah rumusnya: awal + ditambah − akhir). **P-K-20**: PK di tumpukan G2 tak punya jalan ke silo — fungsi ada, pintu tak ada |
| `polishing_process`, `polishing_silo_usage`, `polishing_output_logs` | — | ditulis polishing; dibaca finished_goods (packing), report (HPP beras) | rendemen = beras / PK terpakai bergantung pada snapshot silo yang benar (P-K-11); tak ada jalur undo (P-K-10 sisi G2) |

Kesamaan keempat temuan: masing-masing adalah **dua catatan di dua tempat
yang harus dicocokkan** (transfer ↔ intake; intake ↔ silo; snapshot silo ↔
stok silo; tumpukan ↔ silo). Bila transfer PK menjadi satu peristiwa dalam
satu transaksi (Tahap 3) di dalam satu modul `produksi` (Tahap 4,
`gudang2→produksi`), keempatnya kehilangan tempat lahirnya. Ukurannya
sudah ada: `scratch-a1/r01` (PK luar ganda) dan `r03` (transfer ganda) —
keduanya 0/20 hari ini dan wajib tetap 0/20 sesudah penyatuan.

## 4. Tujuh modul yang diusulkan — ke mana 76 tabel pergi

Awalan tabel mengikuti artifact. **Status**: *jelas* (satu penulis, satu
fungsi), *usul* (saya menempatkannya, alasannya bisa dibantah), **TANYA**
(keputusan pemilik — ADR §7). Mengganti nama tabel adalah keputusan
tersendiri (ADR §7 butir 2); awalan di sini ilustrasi.

### 4.1 `identitas` — `orang_*`

| Tabel | Status | Catatan |
|---|---|---|
| `users` | jelas | satu orang satu baris; `users.status` = SATU saklar nonaktif (`hmu_identitas.masuk.nonaktifkan`), dibaca kelima app tiap permintaan (Tahap 2 selesai 13 Sep) |
| `produksi_akun` | jelas | AKUN BERSAMA (model `hmu_identitas.model.Akun`; nama tabel tak diganti, chain migrasi masih produksi): kredensial + sesi + `token_version` untuk produksi, Meja, Gudang 2, DAN timbangan (Tahap 2) |
| `timbangan_akun` | jelas | sejak Tahap 2: PROFIL pos timbang — `akun_id → produksi_akun` (tertaut) atau kredensial lama (belum tertaut); kode perangkat & sasaran FK riwayat timbang tetap di sini |
| `kantor_role`, `kantor_user_role` | usul | tangga peran & penugasan orang→peran |
| `kantor_grant` | TANYA | izin per domain alat Kantor (K-09): peran (identitas) atau izin alat (agen)? |

### 4.2 `timbang` — `timbang_*`

| Tabel | Status | Catatan |
|---|---|---|
| 12 tabel: `timbangan_transaksi`, `_penimbangan`, `_muatan`, `_foto`, `_cetak`, `_pemeriksaan`, `_kendaraan`, `_tara_standar`, `_nomor`, `_audit`, `_jenis`, `_config` | jelas | ditulis timbangan; `timbangan_transaksi` dibaca produksi lewat kontrak tertulis |
| `timbangan_supplier_profil`, `timbangan_skor_supplier` | usul | profil & skor pemasok versi timbang (yatim hari ini) |

### 4.3 `produksi` — `produksi_*` (Gudang 1 DAN Gudang 2 sebagai dua tahap)

| Tabel | Status | Catatan |
|---|---|---|
| Tahap G1: `purchase_batches`, `drying_lots`, `drying_lot_batches`, `drying_moisture_logs`, `drying_cooling_logs`, `silo_storage`, `silo_moving_logs`, `milling_process`, `milling_process_sources`, `milling_progress_logs`, `milling_qc_logs` | jelas | gabah → PK |
| Transfer: `internal_transfers` | jelas (dulu TANYA) | G1 → G2 adalah tahap DI DALAM modul, bukan pergerakan antar-modul — ADR §4.1 |
| Tahap G2: `pk_purchase_batches`, `pk_gudang2_intakes`, `pk_tumpukan_to_silo`, `polishing_process`, `polishing_silo_usage`, `polishing_output_logs` | jelas | PK → beras & hasil samping |
| `jeda_proses` | jelas (dulu TANYA) | berhenti sementara pengeringan/giling/penyosohan — semuanya proses produksi |
| `pk_rejections` | jelas (mati) | calon dibuang |
| `milling_pk_routing`, `pk_stock_gudang1` | — | sudah dibuang (0033) |
| `purchase_batch_verifications`, `milling_process_verifications`, `pk_purchase_verifications` | TANYA | barisnya menempel proses fisik, isinya harga/output final/QC — lihat §4.6 |
| `milling_qc_logs` | usul | mutu adalah sifat proses, bukan uang; tetap di produksi |

### 4.4 `persediaan` — `sedia_*`

| Tabel | Status | Catatan |
|---|---|---|
| `finished_goods_stock`, `byproduct_stock`, `outgoing_records`, `outgoing_items`, `packaging_purchases`, `packaging_losses` | jelas | barang jadi, hasil samping, kemasan, keluar |
| `product_skus`, `packaging_materials`, `package_sizes`, `brands`, `rice_quality_standards` | usul | master persediaan; bisa juga modul `master` (§4.8) |

### 4.5 `uang` — `uang_*`

| Tabel | Status | Catatan |
|---|---|---|
| `byproduct_prices` | jelas | harga acuan hasil samping |
| `purchase_batch_verifications`, `pk_purchase_verifications`, `milling_process_verifications` | TANYA | lihat §4.6 |
| *(kolom)* `internal_transfers.hpp_per_kg`, `pk_gudang2_intakes.hpp_per_kg`, `finished_goods_stock.hpp_per_kg`, `packaging_purchases.harga_*` | TANYA | snapshot rupiah di tabel modul lain — yang membuat `uang` tak bisa dipotong bersih |

### 4.6 Catatan: verifikasi harga & output

Tiga tabel verifikasi berisi dua hal sekaligus: penetapan angka FISIK final
(berat output giling, potongan kg, QC PK) dan angka RUPIAH (harga/kg, total).
Timbangan sengaja tanpa kolom harga; Meja adalah satu-satunya yang boleh
melihat rupiah. Tiga kemungkinan, tak diputuskan di sini: (a) tetap di
`produksi` dengan kolom rupiah dibaca hanya lewat `uang.layanan`; (b) pecah
jadi dua tabel; (c) seluruh tabel ke `uang`. ADR §7 butir 7.

### 4.7 `peristiwa` — `peristiwa`, `proyeksi_*` · `agen` — `agen_*`

| Modul | Tabel | Status | Catatan |
|---|---|---|---|
| peristiwa | `activity_logs` | usul | jejak audit tambah-saja — cikal bakal buku besar |
| peristiwa | `peristiwa`, `proyeksi_gabah_masuk`, `proyeksi_pk_luar_masuk`, `proyeksi_pk_masuk_g2`, `proyeksi_transfer_pk`, `proyeksi_pindah_tumpukan_silo` | **ADA** (Tahap 3, 13 Sep) | buku besar + lima proyeksi; cermin tabel lama BERTANDA (`dibatalkan_pada`, migrasi 0052) dan tak pernah dihapus lagi — saringan sesi ORM di `app/models/cermin.py`, SQL mentah menyaring eksplisit |
| peristiwa | `kode_urut` | usul | penghitung atomik penomoran |
| peristiwa | `notifications` | TANYA | tak dibaca siapa pun; peristiwa, agen, atau dibuang? |
| peristiwa/?? | `setelan_pabrik` | TANYA | setelan lintas modul; belum ada modul "setelan" |
| agen | `kantor_sop_dokumen`, `_sop_chunk`, `_aksi_pending`, `_audit_log`, `_chat_riwayat`, `_nomor_dokumen`, `_aturan_email`, `_heartbeat` | jelas | kantor saja |
| agen | `kantor_aset`, `kantor_kartu_pemeliharaan` | jelas (mati) | |
| agen | `kantor_config`, `kantor_llm_usage` | TANYA | dua guard, dua aplikasi, satu anggaran (K-10) |
| agen | `kantor_grant` | TANYA | §4.1 |

### 4.8 Tak punya rumah di tujuh modul — TANYA

| Tabel | Catatan |
|---|---|
| `suppliers`, `pelanggan` | mitra: ditulis produksi, kantor (Kledo), dibaca timbang/produksi/uang/agen |
| `warehouses`, `silos`, `dryers` | alat: ditulis produksi (seed, Pengaturan, Meja), dibaca produksi & timbang(?) |
| Pilihan: modul kedelapan `master`; atau `identitas` → `pihak` (orang + mitra) dan alat masuk `produksi`. |
| `alembic_version*` (4) | infrastruktur — jadi satu di Tahap 4; yang lama di-stamp |

## 5. Yang tidak menyentuh basis data — kontrak HTTP

| Repo | Basis data | Pintu yang dipakai | Konsekuensi |
|---|---|---|---|
| `meja/` | tidak ada | `/internal/meja/*` (masuk, saya, akun, beranda, gudang, kartu, stok, laporan, audit, pengaturan, pengguna, alat), `/api/*` (14 aksi `AKSI_MEJA` + undo), `/api/laporan/*`; header `X-Internal-Token` + `X-Meja-Akun` + `X-Meja-Versi` (+`X-Meja-Lihat`); token = `MEJA_API_TOKEN` | produksi mati = Meja mati (X-23) |
| `gudang2/` | tidak ada | `/internal/meja/masuk|saya|akun/*`, `/internal/gudang2/{beranda,kartu,stok}` (branch `gudang2-api`), `/internal/meja/laporan`, `/api/*` (9 aksi `AKSI_OPERATOR`), `/api/laporan/*`; header & token yang sama dengan Meja | produksi mati = Gudang 2 mati |
| `kantor/` | 15 `kantor_*` + `users`, `suppliers`, `pelanggan` langsung | data pabrik lewat `/internal/produksi/{tanya,hpp,operasional}` (read-only, `INTERNAL_API_TOKEN`) | produksi mati = fitur pabrik Kantor menjawab "tak terjangkau", sisanya jalan |
| `website/` | tidak ada (berkas JSON di `DATA_DIR`) | tidak ada sambungan ke pabrik | berdiri sendiri; tetap terpisah di usulan |

## 6. Daftar "perlu dicek" — bukan keputusan, tetapi fakta yang belum terbukti

1. Kapasitas "Pengering 1": 30.000 (0003 & `services/seed.py`) vs 35.000 (`app/seed.py`).
2. `product_skus` cari-lalu-buat tanpa indeks unik (pola P-K-04/X-20).
3. `packaging_losses` dibaca rumus stok, tak pernah bisa diisi.
4. `notifications` tak dibaca layar mana pun — sisa bot.
5. `pk_rejections`, `kantor_aset`, `kantor_kartu_pemeliharaan`, `timbangan_foto`, `timbangan_skor_supplier` (+ `supplier_profil` tanpa penulis): tabel yatim.
6. Timbangan `hapus_akun` men-NULL-kan kolom FK akun lewat `Base.metadata` — aman hari ini, tetapi loop generik itu akan menulis ke tabel produksi bila kelak ada FK ke `timbangan_akun` di pemetaan.
7. `TABEL_BASELINE` adopsi kantor tak menyebut tiga tabel RBAC.
8. `data_uji._mundurkan` (RAW UPDATE `drying_lots`/`milling_process`) kemungkinan kode mati.
9. Undo tidak menjangkau: `pk_tumpukan_to_silo`, `polishing_*`, `finished_goods_stock`, `outgoing_*`, `packaging_*`, `jeda_proses` — daftar aksi yang Tahap 3 harus tutup dengan peristiwa lawan.
10. Klaim layar produksi "nonaktif berlaku juga di Timbangan" bergantung pada timbangan membaca `users.status` saat login — **terbukti** (`timbangan/routes/auth.py:95-99`, `security.py:225`), tetapi sesi yang sudah terbit tak diputus sampai token-nya habis (T-19 ditutup dengan versi sesi di timbangan sendiri).
