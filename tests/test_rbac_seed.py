"""Sanity katalog RBAC (murni, tanpa DB)."""
from app.kantor.rbac_seed import GRANTS, ROLES

_MODE_VALID = {"none", "read", "write", "owner"}


def test_semua_role_di_grant_ada_di_katalog():
    kodes = {k for k, _, _ in ROLES}
    for role in GRANTS:
        assert role in kodes, f"role '{role}' punya grant tapi tak ada di ROLES"


def test_mode_valid():
    for doms in GRANTS.values():
        for domain, mode in doms.items():
            assert mode in _MODE_VALID, f"{domain}={mode} mode tak valid"


def test_direksi_owner_semua():
    assert GRANTS["direksi"] == {"*": "owner"}


def test_gaji_hanya_role_yang_seharusnya():
    boleh_gaji = {r for r, d in GRANTS.items() if "gaji" in d}
    assert boleh_gaji == {"hr_manager", "office_manager"}  # + direksi via '*'


def test_staff_hr_tanpa_gaji():
    assert "gaji" not in GRANTS["staff_hr"]
