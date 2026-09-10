---
name: peran-superadmin-tuntas
description: "Tangga peran akhirnya punya puncak: pemilik = superadmin sejak 10 Sep 2026; produksi mengunci orang/akun/alat; Kantor mengakui superadmin dan di-deploy lewat railway up"
metadata:
  type: project
---

Sampai 10 September 2026, peran `superadmin` ada di kode tetapi **tak pernah dipakai di produksi**: satu-satunya akun adalah `admin` milik pemilik (wahid). Sebabnya bukan kelalaian melainkan dua penghalang nyata.

1. **Penjaga "akun tertinggi terakhir" di produksi membandingkan NAMA peran** (`peran != "admin"`), jadi Admin terakhir yang mau NAIK ke Super Admin ikut ditolak. Puncak tangga tak bisa diisi siapa pun. Sekarang membandingkan TINGKAT — lihat [[basis-data-bersama]] untuk aturan lintas layanan.
2. **Kantor menolak `superadmin`** karena delapan gerbangnya menulis `role == "admin"` harfiah. Menaikkan peran pemilik justru mematikan aksesnya ke Gmail, GajiHub, IT aset, pengetahuan, Kledo, dan data keuangan. Terbukti nyata: pemilik naik pangkat, botnya langsung menolak.

**Keadaan sekarang:** pemilik = `superadmin`, satu-satunya akun di produksi. Produksi mengunci Kelola pengguna, Alat dryer & silo, dan Hapus data uji ke Super Admin saja, dengan jaring pengaman — selama tak ada satu pun Super Admin AKTIF, Direksi tetap diterima, supaya pabrik tak pernah terkunci dari dalam. Setelan kerja (target kadar air, sebab berhenti, sakelar mutu) sengaja TETAP milik Direksi.

**Belum ada akun tingkat tertinggi kedua.** Seluruh pabrik bergantung pada satu akun. Ini risiko yang sudah disampaikan dan belum ditutup.

**Jebakan yang memakan dua kali kirim: bentuk tanda kurung.** Perbaikan peran Kantor (`8d331d3`) menyapu `== "admin"` dan `in ("admin", "staff")` lalu dinyatakan tuntas. EMPAT gerbang di `app/kantor/bot.py` menulisnya sebagai himpunan — `{"admin", "staff"}`, kurung KURAWAL — jadi tak tersentuh. Yang lolos justru gerbang TERLUAR (`handle_message`, `/start`, `/whoami`, tombol persetujuan), sehingga bot menolak SETIAP pesan dengan "⛔ Kantor AI khusus Direksi/Staff kantor" sementara pemeriksaan di dalamnya menjawab "boleh". Uji penjaganya LULUS karena daftar polanya teks tetap tanpa bentuk kurawal — uji penjaga yang polanya kurang lengkap lebih buruk daripada tak ada uji, sebab kepastian palsu menghentikan pencarian. Sekarang polanya regex (kurung biasa/kurawal/siku) dan pola itu sendiri diuji pada contoh yang dulu lolos. Pelajaran umum: saat menyapu pemakaian harfiah, cari dengan regex yang menerima semua bentuk sintaks, lalu buktikan penjaganya gagal pada kasus lama.

**Cara deploy Kantor — berbeda dari produksi.** Layanan `kantor` TIDAK tertaut GitHub: metadata deploy-nya kosong. Deploy-nya `railway up --service kantor` dari `~/Developer/Hadi Mulya Systems/kantor`, yang mengunggah pohon kerja lokal (ada submodule `core`, pastikan bersih). Bandingkan produksi & uji yang justru auto-deploy dari push ke branch `main`/`uji` — lihat [[railway-deploy]] dan [[pisah-kantor-produksi]].

**Cara memeriksa versi Kantor yang benar-benar berjalan:** `railway ssh --service kantor -- sh -c 'grep ...'`. Metadata Railway tak menyebut commit untuk layanan yang tak tertaut git, jadi isi kontainer adalah satu-satunya kebenaran.
