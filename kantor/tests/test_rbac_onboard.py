"""Sanity RENCANA onboarding (murni, tanpa DB)."""
from app.kantor.rbac import role_valid
from app.kantor.rbac_onboard import RENCANA, _coarse


def test_semua_role_di_rencana_valid():
    for key, (nama, roles, atasan) in RENCANA.items():
        assert roles, f"{key} tak punya role"
        for r in roles:
            assert role_valid(r), f"{key}: role '{r}' tak valid"


def test_atasan_ada_di_rencana():
    for key, (nama, roles, atasan) in RENCANA.items():
        if atasan is not None:
            assert atasan in RENCANA, f"{key}: atasan '{atasan}' tak ada"


def test_coarse_role():
    assert _coarse(["direksi", "pegawai"]) == "admin"
    assert _coarse(["office_manager", "pegawai"]) == "staff"
    assert _coarse(["komisaris"]) == "staff"


def test_direksi_dua_orang():
    direksi = [k for k, (n, r, a) in RENCANA.items() if "direksi" in r]
    assert set(direksi) == {"wahid", "miftah"}
