---
name: basis-data-bersama
description: "TIGA tabel yang tampak milik produksi padahal dipakai bersama Timbangan/Kantor — dan mengapa TRUNCATE CASCADE pernah menyapu seluruh tiket timbang"
metadata:
  type: project
---

Satu Postgres dipakai **produksi, timbangan, dan kantor**. Bahayanya bukan tabel yang jelas
milik orang lain (`timbangan_*` mudah dikenali), melainkan tabel yang **terlihat milik
produksi**:

- **`suppliers`** — `timbangan_supplier_profil.supplier_id` & `timbangan_skor_supplier.supplier_id`
  **WAJIB ISI**. Menghapus supplier merusak data Timbangan.
- **`kantor_config` & `kantor_llm_usage`** (didefinisikan di `app/ai/models.py`, nama warisan
  saat serepo) — **kill-switch & BATAS BIAYA LLM**, dipakai bersama layanan Kantor.
  Mengosongkannya = mereset pengaman biaya kedua aplikasi. Bandingkan memori
  [[bulk-llm-audit-cost]]: batas biaya pernah membuat bot offline sehari penuh.

**PELAJARAN MAHAL — `TRUNCATE ... CASCADE` MERAMBAT KELUAR.** `Base.metadata` produksi memuat
0 tabel `timbangan_*`, dan saya menyimpulkan penghapusan "tidak mampu" menyentuh tiket. SALAH:
CASCADE mengikuti foreign key yang **MASUK**. `timbangan_transaksi` menunjuk ke `suppliers`,
`purchase_batches`, `pk_purchase_batches` → sekali jalan, 2 tiket jadi 0. Ketahuan HANYA
karena diuji sungguhan (`scripts/uji_mode_uji.py`), bukan dari membaca kode.

**Aturan untuk penghapusan massal apa pun di repo ini:**
1. JANGAN `TRUNCATE ... CASCADE`. Postgres juga menolak TRUNCATE polos selama constraint-nya
   ada — walau barisnya sudah NULL — jadi TRUNCATE memang alat yang salah. Pakai `DELETE FROM`
   urut anak-dulu dari `Base.metadata.sorted_tables`.
2. Hitung jalan keluar dari basis data yang HIDUP (`pg_constraint`), bukan daftar tangan:
   yang menunjuk justru tabel aplikasi lain, tak terlihat dari kode produksi.
3. Tautan masuk yang boleh kosong → di-NULL-kan dulu (untuk tiket, ini justru hasil yang
   diinginkan: tiketnya bebas & bisa dicatat ulang). Yang WAJIB ISI → TOLAK seluruh operasi.
4. Produksi hanya MEMBACA tabel timbangan (12 baca, 0 tulis) — pertahankan itu.

**Mode uji** (`app/web/mode_uji.py`, live sejak 2026-09-05, VERSI 31): mati kecuali
`MODE_UJI=1` di environment — GET & POST sama-sama 404, bukan sekadar tombol disembunyikan.
Super Admin saja, menuntut kalimat `HAPUS DATA UJI` diketik persis, pita kuning di tiap layar
saat menyala. **Belum dinyalakan di Railway** — pemilik yang menyalakannya sendiri.
Dipertahankan: akun/orang, alat (gudang·silo·dryer), daftar acuan, dan ketiga tabel bersama
di atas.
