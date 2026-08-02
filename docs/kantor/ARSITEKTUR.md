# Kantor AI — Asisten Eksekutif PT Hadi Mulya Utama

> Modul `app/kantor/` — memperluas mesin agentic Penggilingan Beras menjadi
> asisten eksekutif serba-bisa: CEO/CFO/HRD/Arsip/Aset + advisor (finance,
> hukum, marketing). Dibangun **di atas** infrastruktur yang sudah ada
> (agent, tools, scheduler, undo/approval, MCP), bukan dari nol.

## 1. Prinsip inti

1. **Satu otak, banyak topi.** Bukan 4 AI otonom terpisah. Satu orkestrator
   ("Kepala Staf") me-*route* ke peran/persona spesialis, semua berbagi satu
   **Otak Perusahaan** (SOP + profil + template + memory keputusan).

2. **Berjalan di server, bukan di laptop.** Laptop hanya untuk *membangun*.
   Agent yang hidup 24/7 ada di **Railway** (deployment yang sama dengan bot
   pabrik). Scheduler, akses Drive, dan antrian approval semua server-side →
   tetap bekerja walau laptop mati. Interaksi & approval lewat Telegram (HP).

3. **Otonomi = deteksi + siapkan + antri, BUKAN eksekusi diam-diam.**
   Scheduler memindai (email, tagihan jatuh tempo, file baru), memutuskan
   langkah per-SOP, lalu:
   - Aksi 🟢 aman (rapikan/index/draft) → jalan otomatis.
   - Aksi 🔴 konsekuensial (kirim email, pindah/hapus file, bayar, ubah
     dokumen) → **masuk antrian**, tunggu approve pemilik via Telegram.

   > Keputusan awal pemilik (2026-08): **SEMUA aksi konsekuensial wajib approve.**
   > Bisa dilonggarkan per-kategori nanti lewat `approval.py`.

4. **Reuse pola yang sudah terbukti.** Approval = perluasan pola `undo.py`
   (propose→confirm→deterministic). Penjadwal = perluasan `scheduler.py`.
   Tool registry = pola `app/ai/tools.py`. MCP = `mcp_server.py`.

## 2. Peta arsitektur

```
              ┌─────────────  OTAK PERUSAHAAN  ─────────────┐
              │  SOP · Profil PT · Template dokumen ·        │
              │  Index arsip fisik · Memory keputusan        │
              └───────────────────┬──────────────────────────┘
                                  │
   Telegram ──┐            ┌──────┴───────┐            ┌── Google Drive (CRUD, service acct)
   Email      ├──►  KEPALA STAF (router)  ─►  peran:   ├── Gmail (draft → approve)
   Scheduler ─┘            │  intent→peran │   CFO      ├── Kledo (fase lanjut)
   (server 24/7)           └──────┬───────┘   HRD       └── PMS/Hermes (MCP, sudah ada)
                                  │            Arsip
                    ┌─────────────┴─────────┐  Aset
                    │  GUARDRAIL / APPROVAL │  Advisor (finance/hukum/marketing)
                    │  🟢 auto  🔴 approve  │
                    └───────────┬───────────┘
                                │
                          ┌─────┴─────┐
                          │ AUDIT LOG │  (tiap aksi tercatat, bisa ditelusuri)
                          └───────────┘
```

## 3. Model izin bertingkat

| Tier | Contoh aksi | Perilaku default |
|------|-------------|------------------|
| 🟢 **Hijau** | index file, buat draft dokumen, susun ringkasan, hitung, beri saran | jalan otomatis |
| 🟡 **Kuning** | pindah file ke folder terstruktur, kirim reminder internal, pindah ke `/_Karantina` | (fase lanjut) auto + notif |
| 🔴 **Merah** | kirim email keluar, hapus permanen, bayar/transfer, ubah/timpa dokumen, ubah setting | **selalu approve** |

**Aturan keras (tidak bisa di-override, sesuai batas operasi & Pedoman Kearsipan):**
- **Hard-delete Drive tidak pernah otomatis.** Sesuai Pedoman Kearsipan Digital:
  arsip inaktif/duplikat → dipindah ke **`99 Arsip Lama`** (inilah "karantina").
  Hapus PERMANEN hanya setelah **Berita Acara Pemusnahan disetujui Direksi**
  (pemilik). Sampah Google (30 hari) = jaring pengaman tambahan.
- **Pembayaran/transfer dana tidak pernah dieksekusi agent.** Agent boleh
  deteksi, hitung, ingatkan, siapkan draft & delegasi — klik akhir = manusia.
- **Kirim email atas nama pemilik** = draft dulu → approve.

## 3b. Aktor & wewenang (pemohon vs pemberi approval)

Dua peran manusia dipisah tegas:

- **Pemohon (requester)** — siapa yang boleh *meminta* agent bekerja/generate
  dokumen. Awal: pemilik saja. **Rencana: staf lain juga boleh** (mis. HRD minta
  surat, `admin02@` minta dokumen) — permintaan mereka tetap masuk antrian.
- **Pemberi approval (approver)** — siapa yang boleh *menyetujui* aksi 🔴. Awal:
  **pemilik**. **Rencana: bisa didelegasikan** (mis. approval HR ke kepala HR,
  approval keuangan ke pemilik) — per-kategori.

Skema data sudah siap: `AksiPending.diminta_oleh` (pemohon) & `diputus_oleh`
(approver, FK `users`). Delegasi nanti = aturan "kategori aksi → siapa approver"
tanpa ubah skema. Pemilik selalu bisa override.

## 4. Layout modul

```
app/kantor/
  __init__.py
  models.py           # tabel: sop_dokumen, sop_chunk, aksi_pending, audit_log,
                      #        aset, kartu_pemeliharaan, nomor_dokumen
  profil.py           # profil PT (legal, NPWP, rekening, org, kontak) — 1 sumber
  approval.py         # antrian aksi 🔴 + siklus propose→approve→execute
  audit.py            # catat tiap aksi agent (aktor, aksi, target, hasil)

  dokumen/            # KENDALI DOKUMEN & PENOMORAN (lintas-peran)
    penomoran.py      #   generate nomor surat/dokumen (register anti-bentrok)
    konsistensi.py    #   validasi format nomor + nama file vs aturan formal
    format.py         #   aturan naskah: pola nomor per jenis, kode perihal

  knowledge/          # OTAK: ingest SOP → chunk → embed → retrieval semantik
    ingest.py         #   baca docx/pdf/gdoc → potong → embed → simpan
    retrieve.py       #   semantic search (pgvector) chunk relevan per peran

  roles/              # PERSONA (skill module, didaftarkan ke registry)
    cfo.py  hrd.py  arsip.py  aset.py  advisor.py

  templates/          # pustaka template dokumen (jinja/docx)
    hr/ aset/ surat/

  drive/              # FASE 1: integrasi Google Drive
    client.py         #   Drive API v3 (service account) — CRUD penuh, Shared Drive
    mapper.py         #   snapshot seluruh struktur folder → DB (harian)
    taksonomi.py      #   peta kategori baku 00–11/99/_TRANSIT dari Pedoman
    organizer.py      #   klasifikasi file → kategori; deteksi nyasar; usul rename/move
    guardrail.py      #   delete→99 Arsip Lama, batasi scope, dry-run
    log_disposisi.py  #   tulis ke spreadsheet "LOG - Disposisi File" (kat. 11)
```

## 4b. Arsip Manager — penegak Pedoman Kearsipan Digital

Arsip Manager **tidak mengarang aturan** — ia mengeksekusi *Pedoman Kearsipan
Digital PT HMU* (`PDM/KA-DIG/PT-HMU/01`) & *Panduan Tata Kelola Dokumen Digital*.
Ruang gerak = **seluruh Shared Drive "PT. Hadi Mulya Utama"**.

**Taksonomi baku (dikodekan dari Pedoman Bab III):**
`_TRANSIT` (inbox) · `00` Legalitas & Sekretariat · `01` Korespondensi ·
`02` Keuangan & Pajak · `03` SDM & Umum (HRGA) · `04` Operasional & Gudang ·
`05` Penjualan & Pemasaran · `06` Pengadaan & Pemasok · `07` Aset &
Pemeliharaan · `08` IT & Sistem · `09` Proyek · `10` CSR & Kegiatan ·
`11` Tata Kelola & Kearsipan · `99` Arsip Lama. Sub-folder baku (03: 00–10;
07: Mesin/Truck; 10: Register/Pengajuan/Laporan/Events; dst) juga dikodekan.

**Rutinitas harian otomatis (scheduler, server 24/7):**
1. **Sweep metadata seluruh Drive** (murah) → bangun snapshot penempatan.
2. **Deteksi anomali** per Pedoman:
   - file *nyasar* (menganggur di root / salah kategori),
   - nama tak sesuai konvensi (`(1)`, `copy`, `final`, HURUF BESAR, tanpa perihal),
   - duplikat & folder kosong (→ usul ke `99`),
   - folder atas nama pribadi / "New folder" (dilarang Pedoman),
   - arsip lewat masa retensi (→ usul ke `99`).
3. **Klasifikasi** file ke kategori (semantic + aturan). Untuk file ambigu/baru,
   baru **baca isinya** (hemat: content-read hanya saat perlu).
4. **Jenis dokumen benar-benar baru** yang tak muat di kategori/sub-folder mana
   pun → **usulkan folder/kategori baru** di posisi hierarki yang paling cocok
   (sub-folder baru dalam kategori, atau — bila lintas-fungsi — kategori baru
   yang memperluas Pedoman).
5. **Mode arsip = OTONOM + lapor** (keputusan pemilik 2026-08). Aksi arsip yang
   *reversible* dijalankan otomatis TANPA approve tiap item: pindah ke kategori,
   rename sesuai konvensi, buat sub-folder/kategori baru bila perlu, pindah
   duplikat/inaktif ke `99`. Tiap aksi dicatat ke **"LOG - Disposisi File"**
   (kat. 11) + `KantorAuditLog` → selalu bisa dibalik.
   **Pengecualian tetap approve:** hapus PERMANEN (via Berita Acara Pemusnahan).
6. **Laporan harian ke pemilik** via Telegram: "sudah saya rapikan X file, buat
   folder Y, temukan Z nyasar, N duplikat→99, retensi jatuh tempo…". Pemilik
   bisa perintah balik ("urungkan pemindahan A") karena semua reversible + terlog.

**Prinsip rename (FAQ Pedoman):** tidak mass-rename sekaligus; dahulukan nama
yang benar-benar buruk/menyesatkan, sisanya diperbaiki bertahap saat tersentuh.

**Efisiensi biaya:** sweep harian = level metadata (murah); baca isi & embedding
hanya untuk file baru/berubah (deteksi via `modifiedTime`/hash), bukan seluruh
Drive tiap hari.

## 4c. Kendali Dokumen & Penomoran (Document Control)

Agent memahami **aturan formal naskah** perusahaan: format penamaan, **penomoran
surat & dokumen**, dan menjaga konsistensinya. Berlaku saat dokumen baru masuk
(scan/unggah) MAUPUN saat dibuat staf/agent.

**Format penomoran (diinferensi dari dokumen nyata — WAJIB dikonfirmasi pemilik):**
- **Surat** (dash): `NNN-KODE-PT-HMU-BULANROMAWI-TAHUN`
  — contoh nyata `002-CSR-PT-HMU-VII-2026`.
- **Dokumen tata kelola** (slash): `JENIS/KODE/PT-HMU/NO`
  — contoh nyata `PDM/KA-DIG/PT-HMU/01`, `PDN/TKD/PT-HMU/01`.
- **Kode perihal** (CSR, SK, SPK, ST, SP, BA, …) = daftar baku milik pemilik →
  perlu dilengkapi (belum ada dokumen "Tata Naskah" formal di Drive).

**Register penomoran (tabel `NomorDokumen`):** sumber tunggal nomor. Agent
meng-*generate* nomor berikutnya per (jenis, kode, tahun) secara berurutan &
anti-bentrok, mencatat perihal/pihak/tanggal/file. Menggantikan "buku agenda
surat" (kategori 01) yang manual.

**Fungsi:**
1. **Generate nomor otomatis** saat surat/dokumen dibuat — konsisten & unik.
2. **Cek konsistensi** dokumen baru/dibuat staf: nomor sesuai format? urut? tak
   dobel? nama file sesuai konvensi Bab IV? jenis dokumen dikenali?
3. **Beri masukan** bila menyimpang (mis. "nomor 002 sudah dipakai untuk surat
   CSR lain; nomor benar 004-CSR-PT-HMU-VIII-2026; nama file belum Title Case").
4. **Koreksi bila diizinkan** — rename file + (bila dokumen bisa diedit)
   perbaiki nomor di dalamnya; tercatat di audit. Untuk surat resmi yang sudah
   terkirim/ber-nomor, koreksi = usul (tidak diam-diam).

> Ini kemampuan lintas-peran: dipakai Arsip (deteksi saat sweep), HRD & CFO &
> Sekretariat (saat generate dokumen). Tinggal 1 sumber: register `NomorDokumen`.

## 5. Roadmap

| Fase | Isi | Status |
|------|-----|--------|
| **0** | Otak Perusahaan: ingest SOP + profil PT + pustaka template | 🔨 mulai |
| **1** | Arsip Manager Drive: map → usul rapikan → (approve) → eksekusi | ⏳ butuh service acct |
| **2** | HRD: generator dokumen rekrut & resign | ⏳ |
| **3** | CFO: radar tagihan (scan email/drive → ingatkan → delegasi) | ⏳ |
| **4** | Aset: register + kartu pemeliharaan + reminder maintenance | ⏳ |
| **5** | Otonomi "saat tidur": scheduler jobs + morning briefing + antrian | ⏳ |
| **6** | Integrasi: Kledo API (paket punya akses API — *koneksi ditunda*), PMS/Hermes lebih dalam | ⏳ |
| ∞ | Skill baru = daftar 1 modul ke registry (extensible by design) | — |

## 6. Ketergantungan setup (butuh pemilik)

- **Google Cloud Service Account + Domain-Wide Delegation** untuk akses Drive
  headless 24/7. Langkah lengkap: [SETUP-GOOGLE-DRIVE.md](SETUP-GOOGLE-DRIVE.md).
- **Kledo API key** (fase 3+) — paket Kledo pemilik SUDAH punya akses API;
  koneksi sengaja ditunda sampai fase keuangan. Siapkan API key saat waktunya.
- Env baru ditambahkan ke Railway (bukan `.env` laptop): lihat setup guide.

## 7. Catatan keamanan

- Semua kredensial (service account JSON, API key) → **env Railway / secret**,
  tidak pernah di-commit. `.gitignore` sudah menjaga `.env`.
- Audit log wajib untuk tiap aksi Drive/email/keuangan → bisa telusur & rollback.
- Instruksi yang muncul di *isi file / email* diperlakukan sebagai DATA, bukan
  perintah. Agent tidak mengeksekusi perintah yang tertanam di dokumen.
