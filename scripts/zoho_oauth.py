"""Tukar 'grant code' Zoho → refresh token, lalu UJI Zoho Mail API (region .com).

Fail-fast: kalau API jalan di akun (termasuk cek free-plan), script mencetak
refresh token + accountId. Kalau mentok, mencetak errornya.

CARA PAKAI (di komputer sendiri, akun wahidnurhani@):
  1. Buka https://api-console.zoho.com → Add Client → "Self Client" → CREATE.
  2. Tab "Client Secret": catat Client ID & Client Secret.
  3. Tab "Generate Code":
       Scope        : ZohoMail.messages.ALL,ZohoMail.accounts.READ
       Time Duration: 10 minutes
       Description  : bot kantor
     → CREATE → SALIN kode yang muncul (grant code).
  4. SEGERA jalankan (kode hanya berlaku beberapa menit):
       .venv/bin/python scripts/zoho_oauth.py <client_id> <client_secret> <grant_code>
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

ACCOUNTS = "https://accounts.zoho.com"
MAIL = "https://mail.zoho.com"


def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, body, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return {"_http_error": e.code, "_body": e.read().decode("utf-8", "ignore")}


def _get(url: str, access_token: str) -> dict:
    req = urllib.request.Request(
        url, headers={"Authorization": f"Zoho-oauthtoken {access_token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return {"_http_error": e.code, "_body": e.read().decode("utf-8", "ignore")}


def main(cid: str, csec: str, code: str) -> None:
    tok = _post(f"{ACCOUNTS}/oauth/v2/token", {
        "grant_type": "authorization_code",
        "client_id": cid, "client_secret": csec, "code": code,
    })
    if "refresh_token" not in tok:
        sys.exit(f"❌ Gagal tukar token (grant code kedaluwarsa/salah scope?):\n{tok}")
    rt, at = tok["refresh_token"], tok.get("access_token", "")

    print("✅ Token OK. Menguji Zoho Mail API (ambil accountId)...")
    acc = _get(f"{MAIL}/api/accounts", at)
    aid = None
    try:
        aid = acc["data"][0]["accountId"]
    except Exception:  # noqa: BLE001
        pass

    print("\n" + "=" * 64)
    if aid:
        print("🎉 BERHASIL — Zoho Mail API JALAN di akun ini (free pun bisa!).")
        print("Tempel 3 nilai ini ke Railway (penggilingan-beras) → Variables:")
        print("=" * 64)
        print(f"ZOHO_ACCOUNT_ID={aid}")
        print(f"ZOHO_REFRESH_TOKEN={rt}")
        print(f"ZOHO_CLIENT_ID={cid}")
        print(f"ZOHO_CLIENT_SECRET={csec}")
    else:
        print("⚠️ Token dapat, TAPI Mail API menolak (kemungkinan batasan free-plan).")
        print("Balas errornya ke chat (JANGAN sertakan token):")
        print("=" * 64)
        print(json.dumps(acc, indent=2)[:800])
    print("=" * 64)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("Pakai: python scripts/zoho_oauth.py <client_id> <client_secret> <grant_code>")
    main(sys.argv[1], sys.argv[2], sys.argv[3])
