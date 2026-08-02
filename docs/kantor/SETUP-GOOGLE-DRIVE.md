# Setup Akses Google Drive 24/7 (Service Account)

> Tujuan: agent bisa **baca, tulis, pindah, hapus (ke karantina)** file di
> Google Drive `hadimulya.com` secara **headless 24/7 dari server Railway** —
> tanpa login interaktif, tetap jalan walau laptop mati.
>
> Kenapa Service Account (bukan OAuth biasa): OAuth butuh klik "Allow" di
> browser dan token bisa kedaluwarsa → tidak cocok untuk proses server otonom.
> Service Account + **Domain-Wide Delegation** (karena kamu punya Workspace)
> memberi server identitas tetap yang bisa bertindak atas nama akun domain.

---

> ⚠️ **PENTING (temuan 2026-08-02):** Organisasi `hadimulya.com` menerapkan
> Org Policy `iam.managed.disableServiceAccountKeyCreation` (Secure-by-Default)
> → **kunci JSON service account TIDAK bisa dibuat.** Maka rencana kunci JSON di
> bawah TERBLOKIR. **Gunakan METODE OAUTH** (lihat "Alternatif: OAuth" di bawah)
> yang lebih aman & direkomendasikan Google. Bagian A–D di bawah disimpan sebagai
> rujukan bila kelak kebijakan diubah.
>
> **Metode dipakai: OAuth "Internal app" + refresh token.** Server memakai refresh
> token utk akses Drive 24/7 tanpa file kunci. Langkah lengkap di bawah ("SETUP OAUTH").

---

## SETUP OAUTH (metode dipakai) — ± 15 menit, sekali saja

**Tahap 1 — OAuth Consent Screen (Internal).**
1. <https://console.cloud.google.com> → project `hadimulya-kantor-ai` → cari
   **OAuth consent screen** (menu *APIs & Services*).
2. Pilih **Internal** → Create. Isi: App name `Kantor AI`, email support & developer
   = `wahidnurhani@hadimulya.com`. Save & Continue sampai selesai (scope boleh dilewati).

**Tahap 2 — Buat OAuth Client (Desktop).**
1. *APIs & Services → Credentials → + Create Credentials → OAuth client ID*.
2. **Application type: Desktop app**, nama `kantor-ai-desktop` → Create.
3. **Download JSON** (client secret) → simpan aman, jangan commit.

**Tahap 3 — Ambil refresh token (sekali, di komputer sendiri).**
```bash
pip install google-auth-oauthlib google-api-python-client
python scripts/gdrive_oauth.py /path/ke/client_secret.json
```
Browser terbuka → login akun ber-akses Shared Drive → **Allow**. Skrip mencetak
3 nilai (`GDRIVE_OAUTH_CLIENT_ID`, `_CLIENT_SECRET`, `_REFRESH_TOKEN`).

**Tahap 4 — Pastikan akun itu anggota Shared Drive.**
Akun yang dipakai login harus **Content manager/Manager** di Shared Drive
"PT. Hadi Mulya Utama". `wahidnurhani@hadimulya.com` (pemilik) biasanya sudah.

**Tahap 5 — Tempel ke Railway → Variables:**
`GDRIVE_OAUTH_CLIENT_ID`, `GDRIVE_OAUTH_CLIENT_SECRET`, `GDRIVE_OAUTH_REFRESH_TOKEN`,
`GDRIVE_ROOT_FOLDER_ID=0AJRl_owZQrOWUk9PVA`.

---

## LAMPIRAN (rujukan): metode Service Account — TERBLOKIR org policy

## Bagian A — Google Cloud (± 10 menit) — *(rujukan; terblokir org policy)*

1. Buka <https://console.cloud.google.com> → login `wahidnurhani@hadimulya.com`.
2. **Buat / pilih project**, mis. `hadimulya-kantor-ai`.
3. **Aktifkan Google Drive API**: menu *APIs & Services → Library* → cari
   "Google Drive API" → **Enable**.
4. **Buat Service Account**: *APIs & Services → Credentials → Create Credentials
   → Service account*.
   - Nama: `kantor-ai-drive`
   - Selesai (role project boleh dikosongkan — akses diatur di Drive/Workspace).
5. **Buat kunci JSON**: klik service account tadi → tab *Keys* → *Add Key →
   Create new key → JSON*. File `.json` terunduh — **simpan aman, jangan
   commit ke git.**
6. Salin **email service account** (bentuk `...@....iam.gserviceaccount.com`) —
   dipakai di Bagian B. (Client ID/domain-wide delegation TIDAK perlu dgn cara B.)

## Bagian B — Bagikan Shared Drive ke service account (± 2 menit)

> **CARA SEDERHANA & LEBIH AMAN** — mengganti domain-wide delegation. Akses
> service account HANYA ke drive ini, bukan seluruh domain. Tidak perlu buka
> admin.google.com.

Sama seperti membagikan dokumen ke rekan kerja:

1. Salin **email service account** (dari Bagian A — bentuk
   `kantor-ai-drive@<project>.iam.gserviceaccount.com`).
2. Buka Shared Drive **"PT. Hadi Mulya Utama"** di Google Drive.
3. Klik **nama drive di atas → Manage members** (Kelola anggota).
4. Tempel email service account, pilih peran **Content manager** (bisa tulis,
   pindah, hapus-ke-Sampah), lalu **Kirim / Done**.

> Dengan cara ini service account bertindak sebagai *dirinya sendiri* — tak perlu
> menyamar (impersonate) akunmu, tak perlu domain-wide delegation, tak perlu admin.

## Bagian C — Pasang kredensial di server (Railway)

1. Buka isi file JSON service account, salin **seluruh isinya** (satu baris JSON).
2. Di Railway → service (yang menjalankan app) → **Variables** → tambah:

   | Variable | Nilai |
   |----------|-------|
   | `GDRIVE_SA_JSON` | *(tempel seluruh isi JSON service account)* |
   | `GDRIVE_IMPERSONATE` | *(kosongkan — tak perlu dengan cara Bagian B)* |
   | `GDRIVE_ROOT_FOLDER_ID` | `0AJRl_owZQrOWUk9PVA` *(Shared Drive PT. Hadi Mulya Utama)* |

   > Menyimpan JSON sebagai satu env var lebih aman & simpel daripada file di
   > image. App akan mem-parse `GDRIVE_SA_JSON` saat start.

3. **JANGAN** taruh file JSON di repo. `.gitignore` sudah memblok `.env`;
   jangan tambahkan file kredensial ke git.

## Bagian D — Ruang gerak: Shared Drive "PT. Hadi Mulya Utama"

Keputusan pemilik: agent mengelola **seluruh Shared Drive perusahaan**
"PT. Hadi Mulya Utama" (bukan dibatasi satu sub-folder), karena ahli arsip
harus bisa melihat & merapikan seluruh isi sesuai Pedoman Kearsipan Digital.

- **Shared Drive ID:** `0AJRl_owZQrOWUk9PVA`  ← isikan ke `GDRIVE_ROOT_FOLDER_ID`
  (terverifikasi saat pemetaan read-only 2026-08-02).
- Catatan teknis: ini **Shared Drive**, bukan folder My Drive. Klien Drive API
  wajib memakai `supportsAllDrives=true`, `includeItemsFromAllDrives=true`, dan
  `corpora=drive` + `driveId` saat query. Sudah diperhitungkan di `drive/client.py`.
- Akses diberi dengan **menambahkan email service account sebagai anggota**
  Shared Drive (peran *Content manager*) — lihat Bagian B. Tanpa impersonation.
- Agent TIDAK membuat folder `_Karantina` baru; "karantina" = kategori baku
  **`99 Arsip Lama`** sesuai Pedoman. Hapus permanen hanya via Berita Acara.

---

## Setelah selesai

Kabari saya, dan saya lanjutkan Fase 1: `app/kantor/drive/client.py` akan
mem-parse `GDRIVE_SA_JSON`, impersonate `GDRIVE_IMPERSONATE`, dan menyediakan
CRUD berpagar (delete→karantina, dibatasi `GDRIVE_ROOT_FOLDER_ID`, dengan
mode dry-run untuk uji tanpa mengubah apa pun).

**Checklist:**
- [ ] Drive API di-enable
- [ ] Service account + kunci JSON dibuat
- [ ] Email service account ditambahkan sbg **Content manager** di Shared Drive PT
- [ ] `GDRIVE_SA_JSON` diset di Railway (tempel isi file JSON)
- [ ] `GDRIVE_ROOT_FOLDER_ID` = `0AJRl_owZQrOWUk9PVA` (Shared Drive PT HMU)
