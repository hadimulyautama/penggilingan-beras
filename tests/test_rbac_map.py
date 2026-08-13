"""Tes pemetaan resource→domain (murni)."""
from app.kantor.rbac_map import domain_folder, domain_gajihub, domain_mailbox

HR = "1LG642_fjj2N-E7uFdxQLUarZRURkRxRJ"
PAYROLL = "1WwfbsrET_FAl54YHiL3SLyEeGWanzhwT"
SENGKETA = "1v6H72z1tp7-NkI6vd84bDqEIM_xiAxl5"
IT = "1OtrKmw0txv3GQYv_ily6nDuj8ED4eXM5"
ROOT = "root-xyz"


def test_payroll_override_hr():
    # file di dalam Payroll → gaji (lebih spesifik dari HR induknya)
    assert domain_folder([PAYROLL, HR, ROOT]) == "gaji"


def test_hr_umum():
    assert domain_folder([HR, ROOT]) == "hr"


def test_sengketa_dan_it():
    assert domain_folder(["sub-x", SENGKETA, ROOT]) == "sengketa"
    assert domain_folder([IT, ROOT]) == "folder_it"


def test_folder_tak_dikenal():
    assert domain_folder(["a", "b"]) is None


def test_mailbox():
    assert domain_mailbox("finance@hadimulya.com") == "keuangan"
    assert domain_mailbox("ADMIN@hadimulya.com") == "sekretaris"
    assert domain_mailbox("wahidnurhani@hadimulya.com") == "pribadi"
    assert domain_mailbox("x@y.com") is None


def test_gajihub():
    assert domain_gajihub("payroll") == "gaji"
    assert domain_gajihub("presensi") == "hr"
    assert domain_gajihub("apa saja") == "hr"  # default hr
