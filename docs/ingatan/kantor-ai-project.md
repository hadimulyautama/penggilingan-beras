---
name: kantor-ai-project
description: Kantor AI — executive assistant (CEO/CFO/HRD/Arsip/Aset) built atop the rice-mill agentic engine
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-02T16:45:07.596Z
---

Ekspansi besar dari [[penggilingan-beras-project]]: membangun asisten eksekutif
serba-bisa (peran CEO/CFO/HRD/Arsip/Aset + advisor finance/hukum/marketing) di
atas mesin agentic yang sudah ada — reuse [[agentic-layer]], scheduler, undo/approval, MCP.

**STATUS — LIVE (2026-08-02):** Kantor AI berjalan di **bot Telegram sendiri** di
service Railway `penggilingan-beras` — bukan Hermes (Hermes ditinggalkan, lihat
[[hermes-vs-own-bot]]). Bot = **@hmu_hermes_bot** id 8461024136 (token BotFather
lama dipakai ulang, env `BOT_KANTOR_TOKEN`). Kode: `app/kantor/bot.py` (router
'kantor', akses admin/staff) + `app/kantor/agent.py` (loop Sonnet). Migrasi 0016
(7 tabel kantor_) sudah APPLIED di prod DB. **v1 tools:** `panduan_arsip` +
`cek_nama_file` (READ, instan) + `siapkan_surat_tugas` (usul→konfirmasi 'ya'→
terbitkan nomor resmi ST/HR + susun naskah). Semua aksi konsekuensial lewat
konfirmasi (session.kantor_pending / stage 'awaiting_kantor').
**BELUM (next):** Drive move/cari/rename & audit harian _TRANSIT — butuh kredensial
Drive (OAuth refresh token) disetel di service `penggilingan-beras`; ingest SOP ke
otak; lebih banyak jenis surat; Kledo.

**Prinsip yang disepakati (2026-08-02):**
- Satu orkestrator "Kepala Staf" me-route ke peran/persona, bukan 4 AI terpisah.
- Berjalan 24/7 di server [[railway-deploy]] (bukan laptop) — user tegaskan
  "harus tetap jalan walau laptop mati". Approval via Telegram dari HP.
- Otonomi = deteksi+siapkan+antri. User pilih: SEMUA aksi konsekuensial WAJIB
  approve (tier merah) untuk mulai. Selaras pola controlled-write [[agentic-layer]].
- Aturan keras: hard-delete Drive tak pernah otomatis (delete=pindah ke
  /_Karantina); pembayaran/transfer tak pernah dieksekusi agent; email keluar draft→approve.

**Aktor & wewenang (2026-08-02):** pemohon vs approver dipisah. Awal owner saja;
RENCANA staf lain boleh request generate dokumen, approval bisa di owner ATAU
didelegasikan per-kategori. Skema sudah siap (AksiPending.diminta_oleh/diputus_oleh).

**Kledo:** paket user SUDAH punya akses API — tapi koneksi Kledo DITUNDA (fase lanjut).

**Urutan build (user pilih mulai dari):** Fase 0 Otak Perusahaan + Fase 1 Arsip Drive.
Lalu HRD → CFO radar tagihan → Aset → otonomi scheduler → Kledo/PMS.

**Sudah dibuat & TERUJI (Fase 0 + Kendali Dokumen):**
- docs/kantor/: ARSITEKTUR.md, SETUP-GOOGLE-DRIVE.md, TATA-NASKAH-DINAS.md
- app/kantor/models.py: SopDokumen, SopChunk, AksiPending, KantorAuditLog, Aset,
  KartuPemeliharaan, NomorDokumen (prefix `kantor_`); terdaftar di app/models/__init__.py.
- app/kantor/dokumen/: format.py (pola nomor/kode/bulan Romawi), konsistensi.py
  (validasi nomor+nama file, rapikan_nama), penomoran.py (terbit nomor DB anti-bentrok).
  Logika murni TERUJI lulus via scratchpad/cek_dokumen.py (jalankan: PYTHONPATH=proot .venv/bin/python).
- migrations/versions/0016_kantor.py: buat 7 tabel kantor_*. `alembic heads`=0016 (head tunggal),
  rantai valid. BELUM di-apply ke DB (jalankan `alembic upgrade head` di Railway saat deploy).

**Ruang gerak Drive (KOREKSI 2026-08-02):** Shared Drive "PT. Hadi Mulya Utama" yang
BENAR = ID `0AJRl_owZQrOWUk9PVA` — SUDAH tertata rapi persis Pedoman (_TRANSIT + 00..11 + 99
semua ada). ID `0AGr3vsFQm4E8Uk9PVA` = drive LAIN yang berantakan (backup PC karyawan
affifah/miftah/admin02) → urusan migrasi terpisah, BUKAN root agent. GDRIVE_ROOT_FOLDER_ID
= 0AJRl_owZQrOWUk9PVA. Shared Drive → klien Drive API wajib supportsAllDrives/
includeItemsFromAllDrives/corpora=drive+driveId. Karena struktur sudah ada, tugas arsip =
JAGA kerapian (sortir _TRANSIT, tangkap nyasar/nama), bukan bangun dari nol.

**Prinsip "cari sendiri" (user 2026-08-02):** agent harus mencari info sendiri di Drive
yang diberi akses sebelum bertanya ke user. Urutan: brain/knowledge → cari Drive → baru tanya.
Terbukti: agent menemukan sendiri folder NPWP, AKTA KEMENKUMHAM, Pernyataan Pendirian,
Comprehensive Company Profile.docx (belum dibaca detail; NPWP PT kandidat di file
230102279709NPWP.pdf / "NPWP 627248594528000.jpg" — perlu OCR/baca utk pastikan nilai PT vs pribadi).

**KUNCI: user SUDAH punya standar kearsipan formal di Drive** — arsip agent MENEGAKKAN
ini, bukan mengarang:
- "Pedoman Kearsipan Digital - PT HMU" (PDM/KA-DIG/PT-HMU/01) id 1SqUwlVmQZrJYfLiIh68SeYNBKiihoa_l5pxbkcha-Uw
- "Panduan Tata Kelola Dokumen Digital" id 11VYtTMjtvO81kVfcMs6H_P4f27iDW2frH9Bx_ig3ABU
- Taksonomi baku: _TRANSIT(inbox) + 00 Legalitas·01 Korespondensi·02 Keuangan&Pajak·
  03 SDM/HRGA·04 Operasional&Gudang·05 Penjualan·06 Pengadaan·07 Aset&Pemeliharaan·
  08 IT·09 Proyek·10 CSR·11 TataKelola&Kearsipan·99 ArsipLama. Sub-folder baku 03(00-10),07(Mesin/Truck),10.
- Nama file: "Jenis Dokumen - Perihal/Pihak.ext" Title Case, " - ", tanpa (1)/copy/final/tanggal.
- Alur: file baru→_TRANSIT→disposisi→catat ke spreadsheet "LOG - Disposisi File"(kat 11).
- Retensi: keuangan/pajak 10th, legalitas permanen, kontrak +5th, SDM +5th.
- Juga sudah ada: Kartu Pemeliharaan Aset (sheet), SOP IT onboarding/offboarding/serah-terima,
  Jobdesc HRGA (docx), Register/SOP CSR → bahan ingest & template HRD/Aset kaya.

**"Karantina" = kategori 99 Arsip Lama** (bukan folder rekaan). Hard-delete HANYA
via Berita Acara Pemusnahan disetujui Direksi (user). Sampah Google 30hr = jaring.

**Arsip harian (user minta 2026-08-02):** tiap hari baca semua file, deteksi nyasar/
salah tempat/nama buruk/duplikat; boleh BUAT folder/kategori baru di hierarki mana
pun bila ada jenis dok benar-benar baru; LAPOR harian ke user via Telegram. Efisiensi:
sweep harian level metadata; baca isi+embedding hanya file baru/berubah.

**Mode arsip = OTONOM + lapor harian (keputusan 2026-08-02, override approve-all utk
domain arsip saja):** aksi reversible (pindah/rename/buat folder/→99) DIJALANKAN otomatis
tanpa approve per-item, dicatat ke "LOG - Disposisi File" + audit, dilaporkan harian,
bisa diurungkan. Hanya hapus PERMANEN (Berita Acara) yang approve. Domain lain
(email keluar/bayar/hapus) tetap approve-all.

**Kendali Dokumen & Penomoran (user minta 2026-08-02):** agent paham aturan naskah
formal, generate nomor surat/dokumen otomatis (register anti-bentrok, ganti buku agenda
surat manual), cek konsistensi dok baru/dibuat staf, beri masukan, koreksi bila diizinkan.
Pola nomor diinferensi (BELUM ada dok Tata Naskah formal, PERLU user konfirmasi kode perihal):
- Surat (dash): NNN-KODE-PT-HMU-BULANROMAWI-TAHUN, contoh nyata 002-CSR-PT-HMU-VII-2026.
- Dok tata kelola (slash): JENIS/KODE/PT-HMU/NO, contoh PDM/KA-DIG/PT-HMU/01.
Tabel baru rencana: NomorDokumen. Modul app/kantor/dokumen/ (penomoran/konsistensi/format).

**Penomoran DIKONFIRMASI user (2026-08-02):** format surat NNN-KODE-PT-HMU-BulanRomawi-Tahun
BENAR; kode CSR/SK/SPK/ST/SP/BA BENAR; nomor RESET TIAP TAHUN; urutan PER-KODE (default
saya, user belum bantah). Dok tata kelola: JENIS/KODE/PT-HMU/NO (PDM=Pedoman,PDN=Panduan,SOP,IK).
Draf **Pedoman Tata Naskah Dinas** (PDM/TND/PT-HMU/01) dibuat di docs/kantor/TATA-NASKAH-DINAS.md
— berisi kode usulan tambahan (SKET,SU,NK,SPd,SPn,LPJ) yg menunggu persetujuan user.
Belum difinalkan ke Drive kat 11 (nunggu user sahkan + pilih docx/gdoc).

**Template & surat sudah ada di Drive (bahan HRD/Aset):** Template-Surat-Tugas,
Template-Surat-Peringatan-SP1-SP3, Template-Surat-Keterangan-Kerja, Surat-Persetujuan-
Pengunduran-Diri, SK Pengangkatan (banyak), Template-Pelaporan-PHK-BPJS, Panduan-Struktur-
Folder-HRGA, Kartu Pemeliharaan Aset HMU (Excel).

**Retrieval:** langsung SEMANTIC SEARCH (pgvector), bukan keyword. SopChunk.embedding
→ jadi tipe Vector saat build. Root shared drive skrg berantakan (banyak file nyasar +
folder backup PC affifahkhusnul@/miftahnurhani@/admin02@) — kebutuhan nyata.

**Blocker Fase 1 — METODE BERUBAH ke OAUTH (2026-08-02):** Org hadimulya.com memblok
kunci JSON service account (Org Policy iam.managed.disableServiceAccountKeyCreation,
Secure-by-Default). → PAKAI OAUTH: Consent Screen Internal + OAuth Client Desktop, consent
SEKALI sbg akun ber-akses Shared Drive → refresh token → env Railway
GDRIVE_OAUTH_REFRESH_TOKEN/CLIENT_ID/CLIENT_SECRET + GDRIVE_ROOT_FOLDER_ID=0AJRl_owZQrOWUk9PVA.
User sudah buat project GCloud + service account kantor-ai-drive (jadi tak terpakai kalau OAuth).
Alternatif ditolak: matikan org policy (kurang aman). Connector Drive bawaan sesi hanya
read/create/copy → wajib integrasi sendiri. Consent OAuth DIPANDU saat drive/client.py dibangun.

**Ditambah build (2026-08-02, user "lanjut saja kamu urus teknisnya"):**
- app/kantor/drive/taksonomi.py: 14 kategori baku + subfolder + tebak_kategori()
  keyword classifier (TERUJI pada nama file nyata: HRGA→03, faktur→02, dst).
- app/kantor/profil.py: profil PT; data SENSITIF (NPWP/akta/rekening) dibaca dari
  ENV brankas (HMU_NPWP/HMU_NO_AKTA/HMU_TAHUN_BERDIRI/HMU_REKENING_BANK), BUKAN di kode
  (hindari bocor via git). User minta CEO tahu NPWP dll → user harus isi env / kasih angkanya.
- app/kantor/knowledge/: chunker.py (potong markdown+breadcrumb, TERUJI 17 potongan pada
  Tata Naskah), ingest.py (dedup konten_hash, idempoten), retrieve.py (pencarian KATA/ILIKE
  dulu—gratis tanpa model; antarmuka cari() stabil utk upgrade embedding nanti).

**Keputusan hosting/agent (user tanya "pakai Hermes Hostinger atau apa"):** REKOMENDASI —
agent Kantor AI dibangun INTEGRATED di app Railway (tempat bot Telegram, DB, scheduler,
tools sudah ada) karena butuh MENULIS (rapikan Drive, terbit nomor, approval). Hermes di
Hostinger = tetap "konsultan" read-only via MCP (opsional). Jangan pecah otak ke 2 server.

**Semantic search:** ditunda—retrieve pakai keyword dulu (gratis, jalan). Embedding lokal
gratis (multilingual) menyusul sbg peningkatan; pgvector saat itu.

**Ditambah (2026-08-02, "lakukan sesuai rekomendasi"):**
- profil.py diperkaya dari Comprehensive Company Profile.docx: merek (Lospulen/Penyunesia/
  Pulenesia), kemasan 10/25/50kg, mitra BULOG/PERPADI/Preferred by Nature (low-carbon rice),
  produk beras putih sosoh. (Company Profile TAK memuat NPWP/akta/tahun berdiri — itu ada di
  folder NPWP + AKTA KEMENKUMHAM.jpg/Pernyataan Pendirian.jpg = scan gambar, perlu OCR nanti.)
- app/kantor/dokumen/surat.py: penyusun surat resmi (kop+nomor+ttd), meniru Template-Surat-Tugas.
  TERUJI: generate Surat Tugas lengkap (001-ST-PT-HMU-VIII-2026) rapi.

**Format nomor DIPUTUSKAN (user 2026-08-02): GARIS MIRING + DIVISI** →
`NNN/KODE/DIVISI/PT-HMU/BULAN(Romawi)/TAHUN`, contoh `002/ST/HRGA/PT-HMU/VII/2026`.
Urut reset tahunan per (kode+divisi). Kode divisi USULAN: DIR/HRGA/KEU/OPS/MKT/PBJ/IT
(HR=alias HRGA) — tunggu user sahkan. Di NAMA FILE, `/` diganti `-` (slash ilegal di filename).
Sudah diterapkan konsisten: format.py, konsistensi.py, penomoran.py, NomorDokumen (+kolom divisi),
migrasi 0016, Tata Naskah §II/§IV/§VII. Semua tes lulus (16/16).

**AKSES GOOGLE DRIVE SELESAI (user, 2026-08-02):** OAuth Internal + refresh token. User sudah:
consent screen Internal + OAuth Client Desktop, jalankan scripts/gdrive_oauth.py → refresh token,
tempel ke Railway env GDRIVE_OAUTH_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN + GDRIVE_ROOT_FOLDER_ID=
0AJRl_owZQrOWUk9PVA. Login sbg wahidnurhani@ (akun khusus arsip@ opsional nanti). google-api-
python-client==2.198.0 + google-auth==2.56.2 di requirements.txt.

**app/kantor/drive/client.py DIBUAT:** OAuth refresh-token client, Shared Drive params, guardrail
karantina()=pindah ke "99 Arsip Lama" (bukan hapus permanen), dry_run, selftest()=list folder atas.
Import OK; terkonfigurasi()=False lokal (kredensial hanya di Railway=benar). Belum diwire ke bot/scheduler.

**✅ LIVE-TEST DRIVE BERHASIL (2026-08-02):** `railway run --service penggilingan-beras
.venv/bin/python scripts/gdrive_selftest.py` → tersambung, list 14 folder atas Shared Drive PT
(_TRANSIT + 00..11 + 99). Vars OAuth ada di service `penggilingan-beras` (BUKAN mcp). Railway CLI
tertaut (project penggilingan-beras, login wahidnurhani20@gmail.com). Cara uji/pakai Drive dgn
kredensial produksi tanpa expose: `railway run --service penggilingan-beras ...`. Services: 
penggilingan-beras (app), mcp, Postgres.

**OFFBOARDING/RESIGN — SOP user SUDAH matang (temuan 2026-08-02):** folder `06 - Non-Aktif & PHK`
(id 1ZQnv7c9qeuyIjS45ZnFAl0M9LNJgrwnX) berisi kasus per-orang folder `YYYY-MM Nama - Resign/PHK`
(Affifah id 1PUYFWW..., + Widodo, Jarwoto). Affifah punya README-Urutan-Proses.md (authoritative)
+ 8 dokumen bernomor: 1 SPPD, 2 BAST Jabatan, 3 BAST Akses Perbankan(BASTB), 4 Tanda Terima
Penyelesaian Hak(TTPH), 5 Lembar Clearance, 6 Paklaring, 7 Sertifikat Kompetensi, 8 Piagam Penghargaan.
ATURAN KONTROL PENTING: Paklaring(#6) DITAHAN sampai clearance+akses bank tuntas; BAST bank diteken
hari kerja terakhir; "SELESAI"=final+diteken+scan diarsip balik; isi 4 dok ttd tak diubah tanpa Direktur;
hal hukum→konsultasi Disnaker. → Fitur resign HARUS ikuti README ini (bukan daftar umum). Template
pendukung: Template-Pelaporan-PHK-Penonaktifan-BPJS, Surat-Persetujuan-Pengunduran-Diri, dll.
Uji konsistensi: jawaban umum Claude ~75% benar tapi lewatkan BAST-bank/Sertifikat/Piagam + aturan tahan-Paklaring.

**SOP MASTERY belum tuntas (2026-08-02):** ~25 SOP di Shared Drive, baru 2 dibaca (Kearsipan
Digital, Tata Kelola Dok). Belum di-ingest ke brain. Inventaris per divisi: Kearsipan(digital/
fisik-2versi), IT(onboarding-offboarding/serah-terima/backup/akun), HR(SOP-HR/struktur-folder),
Keuangan(Invoice/Rekonsiliasi/Bayar Transfer/Cash/Kas Keluar x2), Penjualan(Kirim/Ambil),
Pengadaan(Order/Seleksi Supplier), Operasional(Pembelian PK/Sampling/Muat/Bongkar/Stok/Data
Produksi), CSR(Penyaluran/Pameran HPS). RED FLAGS metadata: DUPLIKAT/versi ganda (SOP Pembelian
PK & Sampling ada 2024+2025; Kearsipan Fisik Doc+Word v1.1; Serah-Terima IT Doc+.html); banyak
SOP lama Apr-2024; nama "...HPS DISHANPAN FINAL.pdf"; SOP kemungkinan belum bernomor Tata Naskah.
Rencana: audit per-divisi → draf selaras → sahкан bersama (JANGAN timpa dok resmi sepihak — lihat
[[sop-mastery-principle]]). Folder induk SOP HR=180qQD..., Keuangan=15YXPc..., SOP BARU ops=1EUvDd...

**AUDIT HR (batch 1, 2026-08-02) — SOP HR user SOLID & self-consistent.** Baca SOP-HR.docx
(SOP-01 Rekrutmen, SOP-02 Cuti via app GajiHub 12hr/th, SOP-03 Disiplin SP1-3 @6bln) +
Panduan-Struktur-Folder-HRGA.docx (folder 00-10 + alur onboarding/offboarding + kode §C).
KOREKSI penilaian sebelumnya: BPJS (§D langkah 6) & akses email/digital (§E) SUDAH ADA di SOP —
gap hanya di eksekusi kasus Affifah (dok 5-8 tak diberi kode, tak ada dok BPJS di folder). 
INKONSISTENSI NYATA: (1) divisi = `HR` bukan HRGA (dok+guide pakai HR) → mesin dibalik ke HR kanonik,
HRGA jadi alias; (2) DIGIT: guide HRGA bilang 3 digit (001) tapi dok asli 2 digit (01) → PILIH SATU
(aku pakai 2 digit=dok nyata, PERLU KONFIRMASI user, guide perlu diupdate). Kode HR LENGKAP diadopsi:
SPPD/BAST/BASTB/TTPH/CLR/PKL/SKK/PGH/PKWT/PKWTT (format.py KODE_BAKU + Tata Naskah §III). Cuti via
GajiHub = integrasi masa depan (spt Kledo). Semua tes lulus (16/16).

**AUDIT KEARSIPAN FISIK (batch 2, 2026-08-02):** KOREKSI flag "duplikat" — Google Doc (ringkas)
vs Word v1.1 (lengkap) = SAMA versi 1.1, dua format SENGAJA, konsisten satu sama lain. Pedoman
Fisik SANGAT bagus. TEMUAN UTAMA: sistem FISIK (kode 01-09) & DIGITAL (00-11) penomoran BEDA →
nomor sama arti beda (03=Perpajakan fisik vs SDM digital; 07=SDM fisik vs Aset digital; 08=Aset
fisik vs IT digital). Pedoman sadar tapi hanya map 1 contoh. → DRAF docs/kantor/PETA-SILANG-ARSIP.md
(tabel lengkap Fisik↔Digital) dibuat utk disahkan. Minor: kop Pedoman Fisik tak pakai alamat baku
Tegalrejo RT/RW 21/07. Kode aset fisik 08-MSN/KDR/ALT-xx → selaraskan kantor_aset.kode nanti.
Fisik: 9 kategori warna+retensi (UU 8/1997+KUP). Sisa batch: Keuangan(3), Ops, Pengadaan, Penjualan, IT, CSR.

**AUDIT KEUANGAN (batch 3, 2026-08-02) — TERBURUK: 4/6 SOP kosong/rusak.** No.Dokumen skema
`SOP/FN/NN` (beda dari Tata Naskah JENIS/KODE/PT-HMU/NN; FN=Finance vs kode divisi KEU; tanpa PT-HMU).
Status: SOP/FN/01 Invoice=LENGKAP(10 langkah); SOP/FN/04 Rekonsiliasi=LENGKAP(7 langkah); SOP/FN/02
Kas Keluar Kirim=KOSONG(langkah blank); SOP/FN/05 Pembayaran Cash=KOSONG+tujuan "Untuk"; SOP/FN/06
Penerimaan Transfer=KOSONG+tujuan "Untuk memastikan". DUPLIKAT: file "3. SOP Kas Keluar (Langsung)"
isinya SAMA dgn "2. Kas Keluar (Kirim)" (dua-duanya SOP/FN/02 judul "KAS KELUAR (Kirim)") → tak ada
SOP Langsung asli. Numbering GAP (03 hilang). Copy-paste error: Definisi/DOKUMEN "Invoice" nyangkut di
SOP Rekonsiliasi/Cash/Transfer. Title vs filename: SOP/FN/06 judul "Penerimaan" tapi file "Pembayaran".
Org roles aspiratif (Dir Keuangan/Pemasaran/Operasional/Komisaris) — mungkin ≠ realita (Wahid Dirut).
RENCANA: draf ulang 3 SOP kosong (Kas Keluar, Bayar Cash, Terima Transfer) pakai best practice +
2 SOP baik sbg template, konfirmasi proses nyata user; beresi duplikat; standарkan skema nomor SOP.

**AUDIT PAJAK + ASET (2026-08-02, urutan CFO 1→2):** NPWP badan=62.724.859.4-528.000 (→brankas
HMU_NPWP). Folder 02 Keuangan&Pajak: subfolder NPWP/Rekening Koran/Laporan Keuangan/SPT/Faktur
Pajak(per-th 2023-26)/BUPOT BULOG(BPU Unifikasi 2025-26)/LIABILITAS/Payment Reminer(typo). GAP pajak:
SPT Badan hanya 2023 (2024/2025 belum ada), TAK ADA SPT Masa PPh21/PPN, tak ada folder bukti bayar
NTPN, tak ada rekonsiliasi fiskal/ekualisasi. PERLU KONFIRM user: (a) PT PKP? (b) PPh21 dilapor bulanan?
(c) SPT Badan 2024 sudah lapor? NYASAR: SK Pengangkatan + Kontrak PKWT Didik Pamungkas (HR) di folder 02
→ pindah ke 03.

Kontrol keuangan BARU (user tetapkan 2026-08-02): bukti setor/tarik WAJIB scan, kas opname mulai ada,
laporan saldo harian mulai ada, payroll WAJIB lengkap (asisten harus MINTA bila kurang). Invoice/faktur/
nota fisik: user tanya perlu scan? → YA (nota termal pudar, pajak 10th, backup). Kledo: no petty cash,
rekonsiliasi & PENYUSUTAN di Kledo (asisten jangan jadi sumber kebenaran penyusutan; sync saat integrasi
Kledo). GajiHub utk cuti/payroll. Tutup buku: user tak paham → dijelaskan (kunci periode Kledo).

**ASET (07 dikonfirmasi, dari Digital):** app/kantor/aset.py: 38 aset REGISTER_AWAL (dari Kartu
Pemeliharaan Aset sheet; kode 07-KEND/07-MSN-G1/G2/BSM) + hitung_penyusutan() garis lurus CEK-SILANG saja.
Model kantor_aset +kolom masa_manfaat_tahun/metode_penyusutan/nilai_residu (migrasi 0016). Fokus register=
OPERASIONAL (pemeliharaan/dok kepemilikan/jadwal servis) krn penyusutan di Kledo. Kartu Pemeliharaan tab
MASIH KOSONG (belum ada log servis). Catatan sheet "fisik 07" perlu dibetulkan (digital 07/fisik 08).

**AUDIT NYASAR + DEDUP DRIVE (2026-08-02) — TULISAN PERTAMA ASISTEN ke Drive BERHASIL:**
Scan full: 350 folder, 1958 file. Root BERSIH (0 nyasar menganggur). Detektor "salah kategori"
keyword TAK ANDAL (11 flag, ~2 benar, banyak salah alarm; enhance baca-isi = opsi 1, ditunda).
196 "nama perlu rapi" TAPI sebagian besar DUPLIKAT. DEDUP pakai MD5 (isi identik) + PER-FOLDER
(duplikat lintas-folder yg disengaja spt KK keluarga DIKECUALIKAN — pelajaran penting).
54 file redundan sefolder dipindah ke 99 - Arsip Lama (id 1VYBdoyZXAicxrdC_DrijzKneeRwAS2iR).
BUG ditemukan saat write pertama: includeItemsFromAllDrives hanya utk files().list, BUKAN
update/create/get → _SHARED dibetulkan (client.py). Pilot 5 file SUKSES & terverifikasi independen
(connector). Verifikasi write: cek folder 99 tak ganda + file benar mendarat. Cara jalankan dedup:
railway run --service penggilingan-beras python scripts/gdrive_dedup_check.py [--apply [N]].
Temuan: "1-31 agustus.xlsx"/"2 juni-31 juli.xlsx" = template KOSONG (MD5=template); "3.SOP Kas
Keluar Langsung"="2.Kirim" identik (mislabel). Perapi nama rapikan_nama diperbaiki (akronim PO/BULOG/
BRI, runtuhkan deret strip). Kartu Pemeliharaan sheet catatan "fisik 07" perlu betul (digital 07/fisik 08).

**OPSI 1 baca-isi (AI classifier) DIBANGUN & TERBUKTI (2026-08-02):** app/kantor/drive/klasifikasi_ai.py
= klasifikasi_isi(nama, isi_teks) → {kode, keyakinan, alasan} via Claude forced-tool (settings.agent_model)
+ prompt taksonomi + kaidah "orang→03 SDM". TERUJI live (ANTHROPIC_API_KEY ada di .env): SK Manager Gudang→
03(0.97), Jobdes Staf Pemeliharaan Mesin→03(0.95), kesepakatan kelompok tani→06(0.9) — perbaiki persis
false-positive keyword. SISA utk fitur penuh: metode ekstraksi isi di drive/client.py (export Google-native/
download+parse docx-pdf) supaya server bisa suapi teks; lalu organizer pass baca-isi utk kandidat salah_tempat
→ laporan nyasar akurat. Belum diwire.

⭐ KOMITMEN TUNTAS (2026-08-02): DETEKTOR NYASAR SUDAH DITINGKATKAN ke baca-isi AI.
Ekstraksi isi: drive/client.py unduh_teks (export Google-native + docx via python-docx +
pdf via pypdf; deps di requirements). Wiring: scripts/gdrive_nyasar_ai.py (keyword pra-saring →
unduh_teks → klasifikasi_isi → hanya AI yakin≥0.8 & beda lokasi = nyasar terkonfirmasi).
TERBUKTI LIVE: 11 kandidat keyword → 10 false-alarm terbantah (semua benar di 03), 2 ragu
(surat izin pemadam→01?) diserahkan manusia, 1 NYASAR NYATA: "kesepakatan kelompok tani.pdf"
09→06 Pengadaan (0.90). Detektor keyword tetap jadi pra-saring murah; keputusan pakai AI.
Belum: (a) pindahkan 1 nyasar terkonfirmasi (butuh persetujuan/atau mode auto); (b) sweep AI
lebih luas (bukan hanya kandidat keyword) utk tangkap nyasar yg keyword lewatkan (mis. mahal—
jalankan terjadwal/bertahap); (c) belum diwire ke organizer sbg fungsi audit_ai() reusable.

**DESAIN DETEKTOR AI DUA-MODE (user 2026-08-02):** (1) AUDIT 1x = scope SELURUH file berkategori,
baca-isi semua → rapikan optimal (mahal, sekali). (2) HARIAN = scope HANYA _TRANSIT — tiap file
baru diklasifikasi AI → dipindah ke folder kategori yg benar (murah, efektif; = disposisi harian
Pedoman otomatis). Urutan: audit 1x DULU (bersihkan semua), baru rutin harian _TRANSIT.
Alat: scripts/gdrive_arsip_ai.py {transit|all|kandidat} [--apply] [--limit N]; reusable
klasifikasi_ai.periksa_entri(c,e)→{kode_ai,yakin,nyasar,...}. Pindah ke kategori root (reversible).
BELUM dijalankan audit 1x (all) — ~1900 file = ~1900 panggilan AI (mahal+lama, ~30-60mnt); sarankan
pilot --limit dulu. Daily transit belum dijadwalkan (scheduler).

**ARSIP FISIK — DIKUASAI & WAJIB PATUH Pedoman Kearsipan Fisik v1.1 (user tegaskan 2026-08-02):**
9 kategori berkode+warna+retensi (01 Legalitas Merah PERMANEN, 02 Keuangan Hijau 10th, 03 Pajak
Kuning 10th, 04 Pembelian Biru 10th, 05 Penjualan Oranye 10th, 06 Produksi Coklat 5th, 07 SDM Ungu
kerja+5th, 08 Aset Abu dimiliki+5th, 09 Umum Hitam/Putih 3th). 3 golongan: VITAL(brankas)/AKTIF/INAKTIF.
7 aturan pemisahan; 08 satu-map-per-mesin (aset >Rp1jt&>1th, kode 08-MSN/KDR/ALT); label [KODE][KAT]—[Sub]—
[Thn]+warna; rutinitas harian/mingguan/bulanan/tahunan; pemusnahan hanya via Berita Acara Direksi.
PENTING: fisik ≠ digital (fisik 01-09 vs digital 00-11 → pakai [[PETA-SILANG]]). PERAN asisten utk fisik =
MEMANDU manusia (tak bisa pegang kertas): kasih tahu ordner/warna/retensi, ingatkan rutinitas & jatuh
tempo pemusnahan, buatkan kartu/label — sesuai visi awal user "memandu arsip fisik".

**HERMES = framework agent penuh (Nous Research), BUKAN skrip read-only (koreksi 2026-08-02):**
Self-host di VPS Hostinger via Docker. Fitur: memori persisten tumbuh, MULTI-CHANNEL bawaan
(Telegram, WHATSAPP, Slack, Discord, Signal, email), tools (web browsing, EKSEKUSI KODE, cron,
sub-agent paralel), Skills Hub (extensible), 200+ LLM termasuk Anthropic/Claude, admin panel browser.
→ ARSITEKTUR BARU yg jadi kuat: HERMES = "badan" (brain+channel WhatsApp/Telegram+memori) di VPS;
Railway app = "tangan" (expose kapabilitas Kantor AI sbg TOOLS via MCP — extend mcp_server.py yg
kini read-only jadi + tool tulis/kantor: Drive ops, generate dok, penomoran, audit arsip, approval).
Hermes panggil tools itu. Ini BUKAN "pecah otak" — tapi agent↔tool-server bersih. Cocok bnyk mau user:
WhatsApp, 24/7 VPS (laptop mati), memori tumbuh, skill nambah. CAVEAT: baru baca halaman marketing —
kematangan/kehandalan nyata perlu divalidasi (user sudah deploy — tanya pengalamannya / pelajari config
& Skills aktualnya). DIPUTUSKAN user 2026-08-02: HERMES-AS-SHELL. Hermes(VPS)=badan (otak+channel WA/Telegram+memori),
Railway=tangan (kapabilitas Kantor AI jadi TOOLS via MCP diperluas). Hermes panggil tools. Rencana
"bot Telegram custom di Railway" DIBATALKAN (diganti Hermes). SAFETY: logika+guardrail (delete→99,
skip draf, approval, penomoran) tetap DI TOOLS (kode kita, deterministik) — Hermes tak bisa lakukan
yg tool tak izinkan. Mekanisme: extend mcp_server.py (kini read-only mill) + tool kantor (Drive ops,
generate dok, penomoran, cari SOP, kategori arsip fisik/digital, audit, approval) → deploy MCP service
Railway → Hermes (yg sudah tahu konsumsi MCP) diarahkan ke tools baru + LLM Claude + channel. PERLU:
pelajari config Hermes aktual (admin panel) utk wiring channel+tools; deploy kantor code ke service MCP
(migrasi 0016 + Drive creds + deps).

**KANAL AKSES (keputusan user 2026-08-02):** asisten dipakai dari HP (bukan laptop; laptop=build saja).
TELEGRAM DULU (gratis, proaktif bebas, sudah ada 3 bot pabrik di Railway) → milestone: bangun antarmuka
Telegram Kantor AI + DEPLOY kode kantor ke Railway (migrasi 0016 + kode) supaya usable 24/7 dari HP.
WHATSAPP WAJIB menyusul (kedepannya) — WA Business API resmi (Meta Cloud, nomor KHUSUS + verifikasi +
biaya + aturan 24jam/template utk proaktif; JANGAN pakai WA tak resmi = risiko banned). Arsitektur kanal
PLUGGABLE: satu orkestrator/otak, channel (Telegram/WA) tinggal colok. Milestone ini prioritas setelah
audit bvpxv7pma selesai.

**ATURAN ARSIP HARIAN (user tetapkan 2026-08-02) — WAJIB dipatuhi rutinitas arsip:**
1. File BARU (dibuat asisten) → SELALU taruh di `_TRANSIT`, sebisa mungkin status DRAF (nama ber-"Draf").
2. Audit harian: file berstatus DRAF (ada "Draf"/"Draft" di nama) JANGAN DISENTUH sampai penanda draf hilang.
3. Audit harian: BACA isi → RENAME sesuai aturan (Tata Naskah/Pedoman) → PINDAH ke folder kategori yg semestinya.
4. SELALU buat LAPORAN tiap selesai; file laporan ditaruh di ROOT Shared Drive "PT. Hadi Mulya Utama"
   (id 0AJRl_owZQrOWUk9PVA). → wire ke gdrive_arsip_ai.py transit mode (skip draf, tulis laporan ke root).

**MULAI BANGUN TOOLS KANTOR di MCP (2026-08-02, user "mulai duluan"):** mcp_server.py +4 tool kantor
(total 13, terverifikasi terdaftar di .venv-mcp): panduan_arsip(nama,isi)→folder digital+ordner fisik
(warna/golongan/retensi, pakai arsip_fisik.py + taksonomi); cek_nama_file; terbitkan_nomor_surat (DB);
buat_surat_tugas. Dibuat app/kantor/arsip_fisik.py: 9 kategori fisik (Pedoman Fisik) + DIGITAL_KE_FISIK
peta-silang + panduan(). Logika teruji (Kontrak→D03/F07 Ungu, Kartu Pemeliharaan→D07/F08 Abu, Faktur
Pajak→note ordner 03). CATATAN: panduan_arsip pakai keyword (bisa salah spt "nota beli gabah"→02 bukan
06/04); Hermes+Claude bisa panggil dgn kategori tepat / nanti tool AI. SISA tools: cari_sop, arsip
audit/dedup, approval, offboarding gen, aset. DEPLOY MCP: requirements-mcp.txt perlu +google-api-python-
client/python-docx/pypdf + Drive creds env + migrasi 0016 di service mcp. Lalu arahkan Hermes ke tools.

**AUDIT AI PENUH SELESAI (bvpxv7pma, 2026-08-02): 99 file nyasar akurat (baca-isi, keyakinan 0.80-0.97),
READ-ONLY belum dipindah.** Pola: ~30 Invoice/rekap "Bu Rara" di 00→05/02; 10 Jobdes Sales/Marketing di
05→03; 8 kontrak proyek/KAK/LAMP/Kontrak Utama di 00→09; ~8 SOP tersebar→fungsi(06/02/05); ~5 NPWP→02;
4 Surat Pernyataan Pemasok halal 00→06; ~6 materi marketing 09→05; 3 Company Profile/Visi-Misi 09→00; dll.
Detektor keyword takkan tangkap ini → validasi penuh opsi 1. SIAP APPLY (gdrive_arsip_ai.py all --apply)
tapi 99 pindah lintas-kategori = tunggu user go / review. NOTE: pindah ke kategori ROOT (bukan subfolder).

**Next:** apply migrasi Railway (alembic upgrade head — cek docker/entrypoint apakah auto); deploy +
jalankan client.selftest() utk bukti sambung Drive; lalu mapper/organizer + laporan harian; sambung
ingest ke Pedoman/Tata Naskah.
