"""Lapisan proaktif Kantor AI: yang berjalan sendiri tanpa diminta.

Briefing pagi, notifier email, radar tenggat, pemantau tagihan, pemroses
invoice, sinkronisasi kontak Kledo, dan pengingat persetujuan.

Sebelumnya berkas-berkas ini duduk di `app/services/` — folder milik sistem
penggilingan — sehingga dari susunan berkas tidak terlihat bahwa ia bagian
Kantor AI. Padahal setiap satunya mengimpor `app.kantor.*` dan tidak ada satu
pun modul penggilingan yang memakainya: pemiliknya tidak pernah ambigu, hanya
letaknya yang keliru.
"""
