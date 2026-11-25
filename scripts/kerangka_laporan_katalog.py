"""Metadata/renderer blueprint katalog publik; tidak mengimpor aplikasi/DB.

Ini helper compiler lokal, bukan serverguard atau resolver izin. Pemilik
runtime memasok LAPORAN_NAV dari pilihan(akun)/siapkan native setelah guard.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
from pathlib import Path

ARTI = 'Aktivitas tahap ini pada periode pilihan.'
_RETURN_DAFTAR = f'''tuple(Laporan("tahap_" + kode, nama, {ARTI!r},
    False, None, berperiode=True) for kode, (nama, *_) in TAHAP.items())'''
_RETURN_BOLEH = '(not lap.uang) or can_see_financials(user)'


def _node(modul, nama, jenis):
    nodes = [n for n in modul.body if isinstance(n, jenis) and getattr(n, 'name', None) == nama]
    if len(nodes) != 1:
        raise ValueError('Kontrak sumber katalog perlu ditinjau: ' + nama)
    return nodes[0]


def _assignment(modul, nama):
    matches = [n.value for n in modul.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == nama for t in n.targets)]
    if len(matches) != 1:
        raise ValueError('Metadata katalog tidak tunggal: ' + nama)
    return matches[0]


def _body_without_docstring(node):
    return [n for n in node.body if not (isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]


def _same_expression(node, expected):
    return ast.dump(node) == ast.dump(ast.parse(expected, mode='eval').body)


def metadata_source(tahap_source: str, laporan_source: str) -> dict:
    """Ambil key+label TAHAP/PERIODE literal setelah kontrak publik terbukti.

    Referensi model pada elemen TAHAP selanjutnya tidak dievaluasi. Jika uang
    atau predicate berubah, hentikan build untuk review; jangan asumsikan role.
    """
    tahap, laporan = ast.parse(tahap_source), ast.parse(laporan_source)
    fields = [n.target.id for n in _node(laporan, 'Laporan', ast.ClassDef).body
              if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
    if fields != ['kode', 'nama', 'arti', 'uang', 'buat', 'berperiode']:
        raise ValueError('Field kontrak Laporan berubah; review compiler diperlukan.')
    daftar = _body_without_docstring(_node(laporan, '_daftar', ast.FunctionDef))
    if (len(daftar) != 2 or not isinstance(daftar[0], ast.ImportFrom)
            or daftar[0].module != 'app.services.laporan_periode'
            or [(a.name, a.asname) for a in daftar[0].names] != [('TAHAP', None)]
            or not isinstance(daftar[1], ast.Return)
            or not _same_expression(daftar[1].value, _RETURN_DAFTAR)):
        raise ValueError('Katalog bukan kontrak uang=False native; review diperlukan.')
    boleh = _body_without_docstring(_node(laporan, 'boleh_lihat', ast.FunctionDef))
    if (len(boleh) != 1 or not isinstance(boleh[0], ast.Return)
            or not _same_expression(boleh[0].value, _RETURN_BOLEH)):
        raise ValueError('Predicate boleh_lihat berubah; review diperlukan.')

    mapping = _assignment(tahap, 'TAHAP')
    if not isinstance(mapping, ast.Dict):
        raise ValueError('TAHAP bukan metadata dictionary literal.')
    daftar_public = []
    for key, value in zip(mapping.keys, mapping.values):
        if (not isinstance(key, ast.Constant) or not isinstance(key.value, str)
                or not isinstance(value, ast.Tuple) or not value.elts
                or not isinstance(value.elts[0], ast.Constant)
                or not isinstance(value.elts[0].value, str)):
            raise ValueError('Key/label TAHAP bukan literal publik.')
        daftar_public.append(dict(kode='tahap_' + key.value, nama=value.elts[0].value,
                                  arti=ARTI, berperiode=True, boleh=True))
    if not daftar_public or len({x['kode'] for x in daftar_public}) != len(daftar_public):
        raise ValueError('Key katalog kosong atau ganda.')
    periode = ast.literal_eval(_assignment(laporan, 'PERIODE'))
    if (not isinstance(periode, tuple) or not periode
            or any(not isinstance(p, tuple) or len(p) != 2
                   or not all(isinstance(x, str) for x in p) for p in periode)):
        raise ValueError('PERIODE bukan pasangan label literal.')
    return dict(daftar=daftar_public, periode=periode)


def metadata(root: Path) -> dict:
    """Root compiler perlu memasukkan dua source ini ke manifest inputnya."""
    return metadata_source((root/'app/services/laporan_periode.py').read_text(),
                           (root/'app/web/laporan.py').read_text())


def navigation_public(native: dict) -> dict:
    """Snapshot presentasi dari owner native; tidak memilih role atau scope.

    Data-tujuan-tab dipakai JS native meski tab visual disembunyikan saat
    aktif=laporan. Jangan menghapus atau membuat pilihan berdasarkan tebakan.
    """
    keys = {'aktif', 'judul', 'jenis', 'detail', 'panduan', 'tab', 'pilihan', 'boleh_alamat'}
    if set(native) != keys or native['aktif'] != 'laporan' or native['detail'] is not False:
        raise ValueError('Perlu snapshot layout katalog native, bukan detail/identitas.')
    if native['pilihan'] != []:
        raise ValueError('Picker katalog native berubah; review diperlukan.')
    for tab in native['tab']:
        if (set(tab) != {'kunci', 'nama', 'href', 'boleh', 'alamat'}
                or type(tab['boleh']) is not bool or not isinstance(tab['alamat'], list)):
            raise ValueError('Tab harus metadata layout native tanpa jumlah/identitas.')
        if (not all(isinstance(tab[k], str) for k in ('kunci','nama','href'))
                or not all(isinstance(p, str) for p in tab['alamat'])):
            raise ValueError('Tab bukan metadata route/label publik.')
    if (not all(isinstance(native[k], str) for k in ('aktif','judul','jenis','panduan'))
            or not isinstance(native['boleh_alamat'], list)
            or not all(isinstance(p, str) for p in native['boleh_alamat'])):
        raise ValueError('Metadata navigasi bukan bentuk publik native.')
    return deepcopy(native)


def render_blueprint(env, *, public: dict, native_navigation: dict, cap: str,
                     tampilan_induk: bool) -> str:
    """Render isi native plus wrapper base yang nyata, tanpa boot app/base.

    Environment/loader/manifest tetap milik integrator. Tidak menyimpan atau
    mengirim keputusan akses dan tidak membuat actor/akun contoh.
    """
    navigation = navigation_public(native_navigation)
    context = dict(public, VERSI=cap, LAPORAN_NAV=navigation, TAMPILAN_INDUK=tampilan_induk)
    template = env.get_template('laporan.html')
    body = ''.join(template.blocks['isi'](template.new_context(context)))
    # Body berasal template native escaped, bukan request HTML atau data.
    return env.get_template('laporan_katalog_blueprint.html').render(
        **context, KATALOG_NATIVE=body)


def source_pins(root: Path) -> dict:
    names = ('app/services/laporan_periode.py','app/web/laporan.py',
             'app/web/laporan_navigasi.py','hmu_tampilan/templates/base.html',
             'hmu_tampilan/templates/laporan.html',
             'hmu_tampilan/templates/_laporan_navigasi.html',
             'hmu_tampilan/templates/_laporan_kontrol.html',
             'app/web/templates/laporan_katalog_blueprint.html',
             'scripts/kerangka_laporan_katalog.py')
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}
