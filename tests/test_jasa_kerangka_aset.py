"""Paket struktur, bukan cache respons atau penulis transaksi."""
from pathlib import Path
import pytest
from app.web.jasa_kerangka_aset import ASET, ROOT, paket_lokal


def dokumen():
    tags = []
    for name, _, tag in ASET:
        tags.append(f'<link rel="stylesheet" href="/static/{name}?v=fixture">' if tag=='style'
                    else f'<script src="/static/{name}?v=fixture" defer></script>')
    return '\n'.join(tags).encode()


def test_paket_memakai_byte_sumber_native_dan_membiarkan_aset_lain():
    from bs4 import BeautifulSoup
    extra=b'<script src="/static/aksi.js?v=fixture"></script><input value="draf">'
    html=paket_lokal(dokumen()+extra)
    doc=BeautifulSoup(html,'html.parser')
    for name, relative, tag in ASET:
        node=doc.select_one(f'{tag}[data-jasa-aset-native="{name}"]')
        assert node and node.string==(ROOT/relative).read_text()
    assert extra in html


@pytest.mark.parametrize('change',['missing','duplicate'])
def test_referensi_hilang_atau_ganda_tidak_dibundel_setengah(change):
    body=dokumen();first=body.splitlines()[0]
    invalid=body.replace(first,b'',1) if change=='missing' else body+b'\n'+first
    with pytest.raises(ValueError):paket_lokal(invalid)
