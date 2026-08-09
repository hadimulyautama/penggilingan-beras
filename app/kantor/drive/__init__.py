"""Integrasi Google Drive/Sheets/Docs/Calendar — dipakai agen bot Kantor.

  - taksonomi.py : peta kategori baku arsip 00-11/99/_TRANSIT
  - client.py    : koneksi + operasi Drive/Sheets/Docs/Calendar (OAuth refresh token)
  - mapper.py    : snapshot rekursif struktur Drive (untuk audit menyeluruh)
  - operasi.py   : operasi BACA tingkat-tinggi (jelajah/cari/baca/audit/agenda)
  - aksi.py      : usulan TULIS (pindah/rename/hapus/buat/edit/acara) → gerbang persetujuan
"""
