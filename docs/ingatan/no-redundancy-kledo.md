---
name: no-redundancy-kledo
description: "Don't rebuild what Kledo (or existing tools) already do — no redundant work"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-02T11:23:20.227Z
---

Prinsip efisiensi (user tetapkan 2026-08-02) untuk [[kantor-ai-project]]:

**Apa pun yang bisa/sudah dilakukan di Kledo, cukup di Kledo saja — jangan
diduplikasi di asisten/SOP.** Berlaku umum untuk semua tool yang sudah dipakai
(Kledo, GajiHub, dll). Asisten hanya MELENGKAPI celah yang tool itu tak tangani.

**Kledo sudah menangani (biarkan di sana, jangan bikin SOP/sistem tandingan):**
pencatatan transaksi kas/bank/penjualan/pembelian, invoice & faktur, rekonsiliasi
bank, buku besar & laporan keuangan, PENYUSUTAN aset, saldo real-time, tutup buku
(kunci periode). GajiHub: cuti/izin & payroll.

**Yang asisten lengkapi (Kledo/GajiHub TIDAK menangani):** otorisasi & limit
approval, kas opname fisik (hitung tunai vs saldo Kledo), arsip fisik dokumen asli
(Pedoman Kearsipan), HR/offboarding, kartu pemeliharaan & jadwal servis aset,
korespondensi, radar jatuh tempo lintas-dokumen.

**Why:** user tak mau pekerjaan redundant; efisiensi. ALASAN KUNCI: nanti asisten
AKAN MENGAKSES KLEDO LANGSUNG (Kledo punya API — fase integrasi). Jadi keuangan
dikerjakan LEWAT Kledo (baca saldo/invoice/jatuh tempo dari Kledo, delegasi),
bukan lewat struktur data/SOP paralel. Membangun ulang = sia-sia begitu Kledo tersambung.

**How to apply:** SEBELUM bikin SOP/fitur/laporan, tanya "apakah Kledo/GajiHub
sudah melakukan ini?" Jika ya → arahkan ke sana, jangan bangun ulang. Cek apakah
tool bisa lampirкан bukti (mis. Kledo attach nota) sebelum menyuruh scan ke Drive.
Terkait [[sop-mastery-principle]] — kuasai SOP, tapi jangan tambah SOP yang Kledo sudah cakup.
