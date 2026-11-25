"""Oracle suffix registry tanpa DB: byte native, identitas, dan keluarga finite."""
import ast
import copy
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup
import pytest

from app.web.tampilan import templates

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tests/pg/test_jasa_bertahap.py'
NAMES = {'_tanpa_host_registry', '_akhir_host_registry_lengkap', '_dokumen_registry_uji'}
TREE = ast.parse(SOURCE.read_text())
NS = {'json': json, 're': re, '__file__': str(SOURCE)}
exec(compile(ast.Module(body=[n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in NAMES], type_ignores=[]), str(SOURCE), 'exec'), NS)
strip_registry = NS['_tanpa_host_registry']

FAMILIES = {
    'pengaturan_detail': 'padi-pengaturan-detail-kerangka',
    'pengguna': 'padi-pengguna-kerangka',
    'beranda': 'padi-beranda-kerangka',
    'muatan': 'padi-muatan-kerangka',
    'fasilitas_parent': 'padi-fasilitas-parent-kerangka',
    'retur_baca': 'padi-retur-baca-kerangka',
}


def fixture():
    native, full, host = NS['_dokumen_registry_uji']()
    registry = json.loads(BeautifulSoup(host, 'html.parser').select_one('#padi-kerangka-langsung').string)
    native = native.replace('data-pindah-konteks="konteks-uji"', 'data-pindah-konteks="konteks-uji" data-pindah-alamat="/pengguna"')
    native = native.replace('<p>Isi native tetap</p>', '<p>Isi native tetap</p><div class="daftar-standar"><div class="daftar-standar__baris"><span class="baris__nama">Nama sintetis</span><a href="/pengguna/12">Ubah</a></div></div>')
    identity = {k: registry[k] for k in ('cap', 'konteks', 'sesi')}
    def value(source, **extra):
        return dict(versi=1, sumber=source, **identity, **extra)
    from app.web.pengaturan_detail_kerangka import aset as details
    meta = details()
    from app.web.pengguna_baca_native import aset as users, katalog
    from app.web.beranda_kerangka import asset as home
    from app.web.muatan_kerangka import asset as load
    from app.web.fasilitas_parent_kerangka import aset as parent, TARGETS
    from app.web.pengaturan_alat_kerangka import aset as tools
    from app.web.retur_baca_kerangka import aset as returns
    data = dict(registry=registry,
        alat=value(tools()['sumber'], targets=['/pengaturan/alat']),
        pengaturan_detail=value(meta['sumber'], targets={'/pengaturan/akses': 'akses'}, columns=meta['references']['columns'], processes=meta['references']['processes']),
        pengguna=value(users()['sumber'], targets={'/pengguna': 'staf-super', '/pengguna/pelanggan': 'pelanggan'}),
        beranda=value(home()['sumber'], references=dict(sapaan='Selamat pagi, pengguna sintetis', tanggal='25 November 2026', scope='Semua gudang', semua_gudang=True)),
        muatan=value(load()['sumber'], permission={'can_record': True}),
        fasilitas_parent=value(parent()['sumber'], targets=list(TARGETS)),
        retur_baca=value(returns()['sumber'], targets=['/retur']))
    data['pengguna_catalog'] = katalog(native, source_address='/pengguna', permission=data['pengguna'])
    assert data['pengguna_catalog']['entries']
    return native, data


def render(native, data):
    host = templates.get_template('_kerangka_langsung_registry.html').render(**data)
    return native.replace('</body>', host + '\n</body>'), host


def test_all_finite_suffix_families_remove_exact_bytes_without_normalizing_native():
    native, data = fixture()
    full, _ = render(native, data)
    assert strip_registry(full) == native
    changed = full.replace('<p>Isi native tetap</p>', '<p>Isi native BERUBAH</p>')
    assert strip_registry(changed) != native


@pytest.mark.parametrize('family', FAMILIES)
def test_each_family_optional_but_explicit_shape_required(family):
    native, all_data = fixture()
    data = {'registry': all_data['registry'], family: all_data[family]}
    if family == 'fasilitas_parent':
        data['alat'] = all_data['alat']
    full, _ = render(native, data)
    assert strip_registry(full) == native


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('mutation', ['missing-session', 'wrong-session', 'wrong-context', 'wrong-cap', 'wrong-source', 'duplicate'])
def test_each_family_rejects_missing_or_wrong_identity_source_and_duplicate(family, mutation):
    native, data = fixture()
    if mutation == 'duplicate':
        full, _ = render(native, data)
        node = BeautifulSoup(full, 'html.parser').select_one('#' + FAMILIES[family])
        # Tambahan inert palsu tetap ditolak, tidak pernah dilepas generik.
        full = full.replace('</body>', str(node) + '\n</body>')
    else:
        data = copy.deepcopy(data)
        if mutation == 'missing-session':
            del data[family]['sesi']
        else:
            key = {'wrong-session': 'sesi', 'wrong-context': 'konteks', 'wrong-cap': 'cap', 'wrong-source': 'sumber'}[mutation]
            data[family][key] = 'nilai-salah'
        full, _ = render(native, data)
    with pytest.raises(AssertionError):
        strip_registry(full)


@pytest.mark.parametrize('mutation', ['unknown-host', 'wrong-order', 'extra-newline', 'catalog-without-permission', 'catalog-wrong-source', 'catalog-invented-entry', 'facility-without-source-guard'])
def test_suffix_rejects_unknown_order_whitespace_and_catalog_or_guard_mismatch(mutation):
    native, data = fixture()
    if mutation == 'catalog-without-permission':
        del data['pengguna']
    elif mutation == 'catalog-wrong-source':
        data['pengguna_catalog']['source_sha256'] = '0' * 64
    elif mutation == 'catalog-invented-entry':
        data['pengguna_catalog']['entries'][0]['alamat'] = '/pengguna/999'
    elif mutation == 'facility-without-source-guard':
        del data['alat']
    full, host = render(native, data)
    if mutation == 'unknown-host':
        full = full.replace('</body>', '<script type="application/json" id="padi-tidak-dikenal-kerangka">{}</script>\n</body>')
    elif mutation == 'wrong-order':
        # Pindahkan satu host yang sah ke ujung: shape benar, urutan salah.
        # Jinja atribut berurutan berbeda dari serializer; ambil byte sumber tepat.
        exact = re.search(r'<script type="application/json" id="padi-beranda-kerangka"[^>]*>[^<]*</script>', full)[0]
        full = full.replace(exact, '', 1).replace('</body>', exact + '\n</body>')
    elif mutation == 'extra-newline':
        full = full.replace(host, host + '\n')
    with pytest.raises(AssertionError):
        strip_registry(full)
