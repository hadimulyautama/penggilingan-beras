"""Pagar untuk pola yang dua kali menghilangkan gudang kerja saat simpan."""
import ast
from pathlib import Path
import pytest


@pytest.mark.parametrize('modul', ['api.py', 'aksi_inventory.py', 'aksi_undo.py'])
def test_endpoint_tidak_memuat_ulang_profil_sebagai_aktor(modul):
    tree = ast.parse((Path('app/web') / modul).read_text())
    wrong = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            call = node.value
            if (isinstance(call.func, ast.Attribute) and call.func.attr == 'get'
                    and len(call.args) >= 2 and ast.unparse(call.args[0]) == 'User'
                    and ast.unparse(call.args[1]) == 'user.id'):
                wrong.append(node.lineno)
    assert not wrong, f'Gunakan aktor efektif pengguna_aksi; profil dimuat ulang pada baris {wrong}'
