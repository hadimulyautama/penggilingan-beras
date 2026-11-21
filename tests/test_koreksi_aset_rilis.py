"""Semua pintu koreksi harus meminta pasangan core/bridge dari rilis yang sama."""
import re
from pathlib import Path
import pytest

AKAR = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('nama', ['sosoh_ringkas.html', 'giling_ringkas.html', 'koreksi_bahan_berjalan.html'])
def test_semua_entrypoint_koreksi_memakai_cap_rilis(nama):
    teks = (AKAR / 'app/web/templates' / nama).read_text()
    urls = re.findall(r'(?:href|src)="(/static/koreksi-[^"]+)"', teks)
    assert any('/koreksi-bahan-berjalan.js?' in u for u in urls)
    assert any('/koreksi-bahan-berjalan.css?' in u for u in urls)
    if nama != 'koreksi_bahan_berjalan.html':
        assert any('/koreksi-di-detail.js?' in u for u in urls)
    assert all(u.split('?', 1)[1] == 'v={{ VERSI }}' for u in urls)
