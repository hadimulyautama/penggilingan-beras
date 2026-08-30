"""Uji pemformatan tampilan — terutama zona waktu.

Angka dan jam di layar adalah satu-satunya bentuk data ini yang dilihat
orang. Salah zona berarti seluruh catatan terbaca salah meski isinya benar.
"""
from __future__ import annotations

from app.timbangan import format as fmt



# ─────────────── Zona waktu tampilan ───────────────

def test_waktu_berzona_ditampilkan_dalam_zona_perusahaan():
    """Postgres mengembalikan UTC; layar harus tetap menunjukkan jam WIB.

    Ini yang membuat "dibuat 15:14" muncul di sebelah "masuk 22:15" untuk
    kejadian yang sama.
    """
    from datetime import datetime, timezone
    utc = datetime(2026, 8, 30, 15, 14, tzinfo=timezone.utc)
    assert fmt.tgl_jam(utc) == "30 Agu 2026 22:14"
    assert fmt.jam(utc) == "22:14"
    assert fmt.iso(utc) == "2026-08-30"


def test_pergantian_hari_ikut_zona_perusahaan():
    """22:00 UTC sudah masuk hari berikutnya di WIB — tanggalnya ikut."""
    from datetime import datetime, timezone
    utc = datetime(2026, 8, 30, 22, 0, tzinfo=timezone.utc)
    assert fmt.tgl_jam(utc) == "31 Agu 2026 05:00"
    assert fmt.iso(utc) == "2026-08-31"


def test_waktu_tanpa_zona_dibiarkan_apa_adanya():
    """Nilai tanpa zona sudah waktu setempat — menggesernya justru salah."""
    from datetime import datetime
    polos = datetime(2026, 8, 30, 22, 15)
    assert fmt.tgl_jam(polos) == "30 Agu 2026 22:15"
