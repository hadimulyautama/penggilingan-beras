# Arsitektur Sistem — PT Hadi Mulya Utama

**Peta tingkat sistem: tiga modul di atas satu fondasi**
Versi 1.0 · 25 Agustus 2026

Dokumen ini menjelaskan bagaimana ketiga modul berdiri, apa yang dipakai bersama, dan aturan yang menjaga agar penambahan modul berikutnya tidak merusak yang sudah ada. Rancangan rinci tiap modul ada di dokumennya sendiri.

---

## 1. Tiga modul

| Modul | Untuk siapa | Isi | Di kode |
|---|---|---|---|
| **Produksi penggilingan** | Operator gudang & staff | Gabah masuk, pengeringan, silo, milling, penyosohan, barang jadi, kemasan, barang keluar | `app/gudang1`, `app/gudang2`, `app/inventory`, `app/services` |
| **AI Agent asisten** | Direksi & manajer | Arsip Drive, Gmail, Kledo, GajiHub, IT aset, pengetahuan, persetujuan | `app/kantor`, `app/ai` |
| **Timbangan** | Petugas pos timbang | Catat timbang, kontrol terhadap nota & surat jalan, monitoring | `app/timbangan` |

Modul adalah **bidang kerja**, bukan proses. Satu modul boleh berjalan di service mana pun; yang membuatnya modul adalah batas tanggung jawab dan batas tabelnya.

---

## 2. Fondasi bersama

Satu-satunya hal yang benar-benar dipakai bersama, dan karenanya tidak boleh diduplikasi:

| Fondasi | Tabel / berkas | Aturan |
|---|---|---|
| **Database** | Satu PostgreSQL di Railway | Semua modul menunjuk `DATABASE_URL` yang sama |
| **Identitas orang** | `users` | Tidak ada master pengguna kedua. Modul boleh menambah tabel kredensial sendiri yang menaut ke sini (`timbangan_akun.user_id`) |
| **Identitas mitra** | `suppliers` | Sumber tunggal supplier & pihak. `kledo_contact_id` disiapkan untuk sinkronisasi Kledo |
| **Hak akses** | `kantor_role`, `kantor_user_role`, `kantor_grant` | Grant `domain → none/read/write/owner`, union antar-peran, ditegakkan di kode |
| **Jejak audit** | `activity_logs`, `kantor_audit_log`, `timbangan_audit` | Hanya bertambah, tidak pernah ditimpa |
| **Guard biaya LLM** | `kantor_config`, `kantor_llm_usage` via `app/ai/guard.py` | **Setiap** panggilan LLM lewat sini: kill-switch, batas bulanan, pencatatan token |
| **Notifikasi** | Bot Telegram + poller | Modul mengirim lewat bot yang sudah ada, tidak membuat bot baru |

> **Prinsip:** fungsi baru menambah kemampuan pada bot dan agen yang ada — **bukan bot baru**. Tiap bot baru berarti token baru, proses baru, dan satu tempat lagi yang bisa mati diam-diam.

---

## 3. Kepemilikan tabel

Tiap tabel dimiliki satu modul. Modul lain boleh **membaca**, tetapi hanya pemilik yang **menulis**.

| Modul | Tabel yang dimiliki |
|---|---|
| Master bersama | `users`, `suppliers`, `warehouses`, `silos`, `dryers` |
| Produksi | `purchase_batches`, `drying_*`, `silo_*`, `milling_*`, `pk_*`, `polishing_*`, `finished_goods_stocks`, `packaging_*`, `outgoing_*`, `internal_transfers`, `byproduct_*`, `brands`, `product_skus` |
| Agen asisten | `sop_dokumen`, `sop_chunks`, `aksi_pending`, `kantor_audit_log`, `kantor_chat_riwayat`, `aset`, `kartu_pemeliharaan`, `nomor_dokumen`, `kantor_config`, `kantor_llm_usage`, `kantor_role`, `kantor_user_role`, `kantor_grant` |
| Timbangan | `timbangan_*` (13 tabel) |

**Modul berbicara lewat database, bukan lewat HTTP.** Tidak ada service yang memanggil service lain. Akibatnya: satu service mati tidak menjatuhkan yang lain, dan memindahkan modul antar-service tidak mengubah kode sama sekali.

Titik temu antar-modul dibuat eksplisit sebagai kolom jembatan, bukan sebagai sambungan diam-diam:

```
timbangan_transaksi.purchase_batch_id     → purchase_batches      (gabah, berat nota)
timbangan_transaksi.pk_purchase_batch_id  → pk_purchase_batches   (PK, berat bersih)
suppliers.kledo_contact_id                → kontak Kledo
timbangan_akun.user_id                    → users
```

---

## 4. Topologi Railway

### Sekarang

```
   ┌────────────────────────┐   ┌────────────────┐   ┌──────────┐
   │ Service: app           │   │ Service:       │   │ Service: │
   │  FastAPI               │   │  timbangan     │   │  mcp     │
   │  produksi + agen       │   │  FastAPI       │   │ read-only│
   │  4 bot Telegram        │   │  PWA pos       │   │ tools    │
   │  poller · 1 replica    │   │  deploy bebas  │   └────┬─────┘
   │  PEMILIK MIGRASI       │   └───────┬────────┘        │
   └───────────┬────────────┘           │                 │
               └───────────────┬────────┴─────────────────┘
                     Service: PostgreSQL
```

### Nanti, bila deploy mulai saling mengganggu

```
   ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────┐
   │ produksi │  │ agen     │  │ timbangan │  │ mcp  │
   └────┬─────┘  └────┬─────┘  └─────┬─────┘  └──┬───┘
        └─────────────┴──────────────┴───────────┘
                    PostgreSQL
```

Pemisahan agen dari produksi **murah**: tiap bot punya token sendiri, jadi cukup satu variabel lingkungan yang menentukan bot mana yang di-polling oleh proses itu. Kode tidak dipecah.

### Aturan operasional

| Hal | Aturan | Alasan |
|---|---|---|
| Replica | Service yang memegang bot Telegram **wajib 1 replica** | Long-polling ganda menghasilkan `409 Conflict` |
| Migrasi Alembic | Satu riwayat, dijalankan **hanya oleh service `app`** saat start | Dua service yang bermigrasi bersamaan akan berebut skema |
| Urutan deploy saat skema berubah | `app` dulu, lalu yang lain | Tabel harus ada sebelum dipakai |
| Token bot | Jangan pernah dipakai dua proses sekaligus | Laptop + Railway dengan token sama = bentrok polling |

---

## 5. Agen adalah konfigurasi, bukan proses

Satu loop agen, banyak bundel tool per domain. Menambah kemampuan berarti menambah **bundel tool**, bukan menambah agen atau bot.

```
                    ┌── bundel produksi   (stok, HPP, milling, pengeringan)
   satu loop agen ──┼── bundel kantor     (arsip, Gmail, Kledo, GajiHub, IT aset)
   (app/ai/agent)   └── bundel timbangan  (rencana: transaksi, tiket terbuka,
                                           skor supplier, pola, tara jatuh tempo)
```

Aturan yang berlaku untuk semua bundel:

1. **Agen membaca, atau mengusulkan.** Aksi tulis tidak pernah dieksekusi agen — diusulkan, dikonfirmasi manusia, lalu dijalankan jalur deterministik yang teruji.
2. **Setiap aksi konsekuensial butuh persetujuan.** Lewat `aksi_pending` dan gerbang konfirmasi.
3. **Semua panggilan LLM lewat `guard.panggil()`.** Tanpa kecuali — itu satu-satunya tempat kill-switch dan batas biaya bekerja.
4. **Hak akses ditegakkan di kode**, tidak pernah hanya di prompt.

---

## 6. Batas yang tidak boleh dilanggar

Berlaku untuk modul mana pun, sekarang maupun yang ditambahkan nanti:

- **Data tidak dihapus permanen.** Yang salah dibatalkan beralasan dan tetap tersimpan.
- **Audit hanya bertambah.** Koreksi menulis baris baru berisi nilai sebelum dan sesudah.
- **Hak akses di kode, bukan di tampilan.** Menyembunyikan menu bukan pengamanan.
- **Tidak ada master tandingan.** Orang dan mitra punya satu sumber kebenaran.
- **Kerahasiaan diwujudkan lewat rancangan.** Operator pos timbang tidak boleh tahu harga, maka modul timbangan tidak punya kolom harga sama sekali — bukan sekadar disembunyikan.
- **Tidak ada bot baru untuk fungsi baru.** Tambahkan ke yang sudah ada.

---

## 7. Dokumen tiap modul

| Modul | Dokumen |
|---|---|
| Timbangan | `docs/timbangan/RANCANGAN.md` · `docs/timbangan/DEPLOY.md` · desain layar pada kanvas · draf SOP gabah kering & revisi Sistem Tara PK |
| Produksi | `Panduan-Penggilingan-Beras.pdf`, `Sistem_Manajemen_Penggilingan_Beras.docx`, `ERD_Penggilingan_Beras.html` |
| Agen asisten | `docs/kantor/` |
| Deploy | `RAILWAY.md`, `DEPLOY-RAILWAY.md` |

---

## 8. Arah ke depan

1. **Timbangan dibangun** sebagai service kedua — ✅ selesai, menunggu deploy (`docs/timbangan/DEPLOY.md`)
2. **Sinkronisasi Kledo** untuk kontak supplier lewat `kledo_contact_id`
3. **Jembatan timbangan → produksi**: transaksi terkunci menaut ke batch pembelian, menghapus input ganda gabah masuk
4. **Bundel tool `timbangan` pada agen**, agar Direksi bisa bertanya soal pos timbang lewat percakapan
5. **Pemisahan service agen dari produksi**, bila deploy mulai saling mengganggu

---

*Dokumen ini peta, bukan aturan mati. Bila kenyataan berubah, dokumen ini yang diperbarui lebih dulu — sebelum kodenya menyimpang diam-diam.*
