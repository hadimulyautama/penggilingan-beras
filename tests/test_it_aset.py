"""Tes IT Accounts (murni, tanpa jaringan Drive)."""
from datetime import date, datetime, timezone, timedelta

from app.kantor import it_aset
from app.kantor.rbac import _domain_mode

_WIB = timezone(timedelta(hours=7))

# Baris sintetis meniru tab Services (A ServiceID..L Catatan)
_SVC = [
    ["S1", "Railway", "Hosting", "akun@x", "SSO", "U01", "-", "U01", "Hobby",
     "$5/bln", "2 Sep 2026", "catatan"],
    ["S2", "Kledo", "Finance", "a@x", "Email", "U01", "-", "U01", "Elite",
     "-", "14 Agu 2027", "-"],
    ["S3", "Domain", "Domain", "-", "-", "U02", "-", "-", "-", "-", "1 Jan 2020", "-"],
    ["S4", "Workspace", "Email", "-", "-", "U01", "-", "-", "Biz", "-", "Bulanan", "-"],
]
_USERS = [["U01", "Ahmad Wahid Nurhani", "a@x"], ["U02", "Elfira", "e@x"]]


def test_tools_cocok_nama():
    assert {t["name"] for t in it_aset.TOOLS} == set(it_aset.NAMA_TOOL)


def test_parse_tgl_indonesia():
    assert it_aset._parse_tgl("2 Sep 2026") == date(2026, 9, 2)
    assert it_aset._parse_tgl("14 Agu 2027") == date(2027, 8, 14)
    assert it_aset._parse_tgl("Bulanan") is None
    assert it_aset._parse_tgl("-") is None


def test_peta_user_dan_nama():
    peta = it_aset._peta_user(_USERS)
    assert peta["U01"] == "Ahmad Wahid Nurhani"
    assert it_aset._nama_user("U01", peta) == "Ahmad Wahid Nurhani (U01)"
    assert it_aset._nama_user("U99", peta) == "U99"  # tak dikenal → apa adanya


def test_fmt_services_filter_dan_pic():
    out = it_aset._fmt_services(_SVC, "kledo", it_aset._peta_user(_USERS))
    assert "Kledo" in out and "Railway" not in out
    assert "Ahmad Wahid Nurhani (U01)" in out  # PIC resolved


def test_fmt_jatuh_tempo_terlewat_dan_berkala():
    out = it_aset._fmt_jatuh_tempo(_SVC, 30)
    assert "TERLEWAT" in out and "Domain" in out  # 1 Jan 2020 selalu lampau
    assert "Berkala" in out and "Workspace" in out  # 'Bulanan' → berkala


def test_fmt_info_tanpa_kredensial():
    out = it_aset._fmt_info("railway", _SVC, [], [], it_aset._peta_user(_USERS))
    assert "Railway" in out and "Hobby" in out
    assert "password" in out.lower()  # disclaimer kredensial tak ditampilkan
    assert "PIC: Ahmad Wahid Nurhani (U01)" in out


def test_fmt_info_tak_ditemukan():
    assert "tak ditemukan" in it_aset._fmt_info("zzz", _SVC, [], []).lower()


def test_rbac_gate_it_tools():
    for nama in it_aset.NAMA_TOOL:
        assert _domain_mode(nama, {}) == ("folder_it", "read")


def test_status_siklus_ditampilkan():
    # baris 14 kolom: ...L Catatan, M Status, N Siklus
    zoho = [["S9", "Zoho", "Email", "-", "-", "U01", "-", "-", "-", "-", "-", "-",
             "dipensiunkan", "-"]]
    out = it_aset._fmt_services(zoho, "", {})
    assert "dipensiunkan" in out
    kledo = [["S8", "Kledo", "Finance", "-", "-", "U01", "-", "-", "Elite", "-",
              "14 Agu 2027", "-", "aktif", "tahunan"]]
    out2 = it_aset._fmt_services(kledo, "", {})
    assert "siklus tahunan" in out2 and "⚠️" not in out2  # aktif → tanpa penanda
    info = it_aset._fmt_info("kledo", kledo, [], [], {})
    assert "Status: aktif" in info and "Siklus: tahunan" in info
