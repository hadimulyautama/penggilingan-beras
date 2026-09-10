---
name: rahasia-railway
description: "JANGAN pernah menjalankan perintah yang mencetak NILAI variabel Railway — private key Gmail pernah bocor ke transkrip lewat `--kv | cut`. Cara aman melihat NAMA saja, variabel Kantor & token bot sudah dibersihkan dari layanan produksi 2026-09-08"
metadata:
  type: feedback
---

**JANGAN menjalankan perintah yang membaca NILAI variabel Railway.** Pada 2026-09-05 saya
menjalankan `railway variables --kv | cut -d= -f1` menyangka hanya nama yang tercetak.
`GMAIL_SA_JSON` bernilai JSON MULTI-BARIS, jadi `cut` yang berbasis baris tak menyaringnya:
**private key service account Gmail tercetak utuh ke transkrip** — kunci dengan izin
`gmail.modify` + `gmail.send` untuk kotak surat perusahaan (domain-wide delegation).

**Why:** alat berbasis baris (`cut`, `grep`, `awk`) tidak aman untuk nilai yang boleh memuat
baris baru, dan rahasia sering begitu. Sekali tercetak, ia masuk transkrip yang tersimpan dan
tak bisa ditarik kembali — satu-satunya pemulihan adalah rotasi kunci, dan itu hanya bisa
dikerjakan pemilik.

**How to apply:**
- Perlu tahu variabel ADA atau TIDAK → **tanya pemilik**, atau baca dari dalam aplikasi.
- Kalau benar-benar harus mendaftar nama: `railway variable list --service <svc> --json` lalu
  parse dengan **json.load** dan cetak `sorted(d.keys())` SAJA. Parser JSON kebal terhadap
  nilai multi-baris; alat berbasis baris tidak. Jangan pernah `--kv`.
- Menulis variabel aman: `railway variable set K=V --skip-deploys`, `railway variable delete K
  --service <svc>` (subperintah `delete` TIDAK menerima `--skip-deploys`/`--yes`; pakai
  `</dev/null` supaya tak menggantung). Buang stdout, nilai keberhasilan dari kode keluar.

**VARIABEL KANTOR MASIH MENEMPEL DI LAYANAN PRODUKSI.** Repo & layanan sudah dipisah
(lihat [[pisah-kantor-produksi]]) tetapi variabelnya tidak. Diperiksa dengan menyisir
`os.getenv`/`os.environ` + field pydantic Settings di kedua repo:
- **17 dipakai produksi** — jangan disentuh (DATABASE_URL, SECRET_KEY, BOT_*, ADMIN_*,
  ANTHROPIC_API_KEY, PRODUKSI_API_*, INTERNAL_API_TOKEN, MODE_UJI, dst.)
- **15 milik Kantor — SUDAH DIHAPUS 2026-09-08** (GMAIL_* termasuk GMAIL_SA_JSON, GDRIVE_*,
  GAJIHUB_API_KEY, KLEDO_API_KEY, VOYAGE_API_KEY). Syarat yang dulu menahannya sudah
  diperiksa: layanan `kantor` memegang NILAINYA SENDIRI, bukan rujukan ke penggilingan-beras;
  `timbangan` & `pos-produksi-uji` tak punya kunci itu sama sekali. Cara memeriksanya tanpa
  membocorkan rahasia: parse JSON lalu cetak nilainya HANYA bila cocok regex rujukan Railway
  (`^\$\{\{[^}]*\}\}$`) — rujukan bukan rahasia, isian asli tak pernah tercetak.
- **3 token bot produksi — SUDAH DIHAPUS 2026-09-08** (BOT_ADMIN_TOKEN, BOT_GUDANG1_TOKEN,
  BOT_GUDANG2_TOKEN, di penggilingan-beras & pos-produksi-uji). Bot produksi dibubarkan;
  lihat [[kantor-bot-consolidation]]. `BOT_KANTOR_TOKEN` di layanan kantor TIDAK disentuh.
- Sesudahnya: penggilingan-beras 14 variabel (dari 42), pos-produksi-uji 7, keduanya tetap
  HTTP 200. `.railway/railway.ts` ikut dibersihkan — di IaC ini "tidak disebut" berarti
  "hapus", jadi daftar yang basi akan MENGHIDUPKAN KEMBALI yang sudah dibuang.
- **6 tak dipakai siapa pun — SUDAH DIHAPUS 2026-09-06** (ZOHO_ACCOUNT_ID/CLIENT_ID/
  CLIENT_SECRET/REFRESH_TOKEN/EMAIL, GEMINI_API_KEY). Aplikasi tetap HTTP 200 sesudahnya.

**Jebakan saat menyisir:** Kantor merakit nama env secara DINAMIS
(`os.getenv(f"GMAIL_PRIBADI{suf}_EMAIL")`), jadi pencarian statis melewatkan
`GMAIL_PRIBADI2_*` dan `GMAIL_PRIBADI_REFRESH_TOKEN` — nyaris saya sebut "tak terpakai".
Selalu grep pola f-string sebelum menyimpulkan sebuah variabel mati.
