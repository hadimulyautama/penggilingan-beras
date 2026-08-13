"""Deny-tests RBAC (murni, tanpa DB) — bukti ISOLASI sesuai aturan pemilik.

Memakai policy in-memory (rbac_seed) via rbac.grants_dari_seed → rbac.boleh.
Set role tiap orang mencerminkan penugasan multi-hat yang direncanakan.
"""
from app.kantor.rbac import boleh, grants_dari_seed

EKA = {"pegawai", "staff_ops", "staff_hr", "staff_legal"}
MUTHIA = {"pegawai", "hr_manager"}
ELFIRA = {"pegawai", "office_manager", "staff_hr", "staff_legal"}
KURNIAWAN = {"pegawai", "legal_officer"}
DIREKSI = {"pegawai", "direksi"}
KOMISARIS = {"komisaris"}
OPERATOR = {"operator"}


def g(roles):
    return grants_dari_seed(roles)


# ── Gaji: hanya Muthia, Elfira, Direksi ──
def test_gaji_muthia_elfira_direksi_boleh():
    assert boleh(g(MUTHIA), "gaji", "read")
    assert boleh(g(ELFIRA), "gaji", "read")
    assert boleh(g(DIREKSI), "gaji", "owner")


def test_gaji_eka_tidak():
    assert not boleh(g(EKA), "gaji", "read")


# ── Keuangan & folder IT: Direksi + Elfira; bukan Eka/Muthia ──
def test_keuangan_dan_it():
    assert boleh(g(ELFIRA), "keuangan", "owner")
    assert boleh(g(ELFIRA), "folder_it", "read")
    assert not boleh(g(EKA), "keuangan", "read")
    assert not boleh(g(EKA), "folder_it", "read")
    assert not boleh(g(MUTHIA), "keuangan", "read")
    assert not boleh(g(MUTHIA), "folder_it", "read")


# ── Sengketa: Direksi, Kurniawan, Elfira, Eka; bukan Muthia ──
def test_sengketa():
    assert boleh(g(KURNIAWAN), "sengketa", "write")
    assert boleh(g(ELFIRA), "sengketa", "read")
    assert boleh(g(EKA), "sengketa", "read")
    assert not boleh(g(MUTHIA), "sengketa", "read")


# ── Staff HR tak boleh menulis gaji; Elfira gaji read-only (bukan write) ──
def test_batas_mode():
    assert not boleh(g(ELFIRA), "gaji", "write")   # office_manager hanya read gaji
    assert boleh(g(EKA), "hr", "write")            # staff_hr boleh admin HR
    assert not boleh(g(EKA), "gaji", "read")


# ── Direksi owner semua; Komisaris read-only oversight ──
def test_direksi_dan_komisaris():
    assert boleh(g(DIREKSI), "legal", "owner")
    assert boleh(g(DIREKSI), "folder_it", "owner")
    assert boleh(g(KOMISARIS), "laporan", "read")
    assert boleh(g(KOMISARIS), "knowledge", "read")
    assert not boleh(g(KOMISARIS), "keuangan", "read")
    assert not boleh(g(KOMISARIS), "email", "write")  # oversight, tak beraksi


# ── Operator minimal: operasional saja ──
def test_operator_minimal():
    assert boleh(g(OPERATOR), "operasional", "write")
    assert not boleh(g(OPERATOR), "hr", "read")
    assert not boleh(g(OPERATOR), "keuangan", "read")
    assert not boleh(g(OPERATOR), "gaji", "read")


def test_role_valid():
    from app.kantor.rbac import role_valid

    assert role_valid("office_manager")
    assert role_valid("operator")
    assert not role_valid("raja")
    assert not role_valid("")


def test_domain_mode_email():
    from app.kantor.rbac import _domain_mode

    assert _domain_mode("baca_email", {"mailbox": "finance@hadimulya.com"}) == ("keuangan", "read")
    assert _domain_mode("kirim_email", {"mailbox": "finance@hadimulya.com"}) == ("keuangan", "write")
    assert _domain_mode("baca_email", {"mailbox": "x@y.com"}) is None  # mailbox tak dikenal


def test_domain_mode_gajihub():
    from app.kantor.rbac import _domain_mode

    assert _domain_mode("payroll_gajihub", {}) == ("gaji", "read")
    assert _domain_mode("karyawan_gajihub", {}) == ("hr", "read")
    assert _domain_mode("setujui_pengajuan", {}) == ("hr", "write")


def test_domain_mode_tak_digate():
    from app.kantor.rbac import _domain_mode

    assert _domain_mode("cari_file", {}) is None
    assert _domain_mode("status_biaya", {}) is None
