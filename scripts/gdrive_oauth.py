"""Ambil REFRESH TOKEN Google Drive (metode OAuth "masuk sekali").

Dipakai karena organisasi memblok kunci JSON service account
(iam.managed.disableServiceAccountKeyCreation). Refresh token memberi server
akses Drive 24/7 tanpa file kunci.

CARA PAKAI (dijalankan SEKALI di komputer sendiri, oleh pemilik):
  1. Buat OAuth Client "Desktop" di Google Cloud → unduh file client secret JSON.
  2. Install dependensi:
        pip install google-auth-oauthlib google-api-python-client
  3. Jalankan:
        python scripts/gdrive_oauth.py /path/ke/client_secret.json
  4. Browser terbuka → login akun ber-akses Shared Drive → izinkan.
  5. Skrip mencetak GDRIVE_OAUTH_CLIENT_ID / _CLIENT_SECRET / _REFRESH_TOKEN.
     Tempel ketiganya ke Variables di Railway. JANGAN commit / kirim ke siapa pun.

Scope: akses penuh Drive (baca/tulis/pindah/hapus-ke-Sampah).
"""
from __future__ import annotations

import json
import sys

SCOPES = ["https://www.googleapis.com/auth/drive"]


def main(secret_path: str) -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        sys.exit("Install dulu: pip install google-auth-oauthlib google-api-python-client")

    flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
    # access_type=offline + prompt=consent → dapat refresh token yang tahan lama.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    with open(secret_path, encoding="utf-8") as f:
        conf = json.load(f)
    conf = conf.get("installed") or conf.get("web") or {}

    print("\n" + "=" * 64)
    print("BERHASIL. Tempel 3 nilai ini ke Railway → Variables:")
    print("=" * 64)
    print(f"GDRIVE_OAUTH_CLIENT_ID={conf.get('client_id', '')}")
    print(f"GDRIVE_OAUTH_CLIENT_SECRET={conf.get('client_secret', '')}")
    print(f"GDRIVE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 64)
    print("Simpan aman. Jangan commit ke git / kirim ke chat.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Pakai: python scripts/gdrive_oauth.py /path/ke/client_secret.json")
    main(sys.argv[1])
