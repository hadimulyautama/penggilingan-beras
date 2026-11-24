"""Opt-in, read-only detail structure. Native report authorization/data stay owned.

No report data is built with empty rows: that would manufacture zero summaries.
Only source labels are read here. The native same-URL GET supplies all values.
"""
from __future__ import annotations

import ast
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qsl

ROOT = Path(__file__).resolve().parents[1]
QUERY = frozenset(('periode', 'dari', 'sampai'))
UNREAD = 'Belum dibaca'


def _assignment(tree, name):
    return next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))


def _literal(node, bindings=None):
    """Bounded source metadata, never eval/import of model/service expressions."""
    bindings = bindings or {}
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in bindings:
        return bindings[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [_literal(n, bindings) for n in node.elts]
        return tuple(values) if isinstance(node, ast.Tuple) else values
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left, bindings), _literal(node.right, bindings)
        if isinstance(left, list) and isinstance(right, list):
            return left + right
    if isinstance(node, ast.Dict):
        result = {}
        for key, value in zip(node.keys, node.values):
            if key is None:
                extra = _literal(value, bindings)
                if not isinstance(extra, dict):
                    raise ValueError('Report group metadata changed.')
                result.update(extra)
            else:
                result[_literal(key, bindings)] = _literal(value, bindings)
        return result
    if isinstance(node, ast.DictComp) and len(node.generators) == 1:
        generator = node.generators[0]
        if isinstance(generator.target, ast.Name) and not generator.ifs and not generator.is_async:
            values = _literal(generator.iter, bindings)
            if isinstance(values, (list, tuple)) and len(values) < 32:
                return {_literal(node.key, {**bindings, generator.target.id: v}):
                        _literal(node.value, {**bindings, generator.target.id: v}) for v in values}
    # The two comprehensions in Sosoh's cols are empty metadata slots, not rows.
    if isinstance(node, ast.ListComp) and len(node.generators) == 1:
        generator = node.generators[0]
        if (isinstance(generator.iter, ast.Name)
                and generator.iter.id in ('bahan_cols', 'hasil_cols')
                and bindings.get(generator.iter.id) == [] and not generator.ifs):
            return []
    raise ValueError('Report structure is no longer literal metadata; review required.')


@lru_cache(maxsize=1)
def _source():
    paths = [ROOT/'services/laporan_periode.py', ROOT/'services/laporan_isi_tahap.py']
    texts = [p.read_text() for p in paths]
    tahap = _assignment(ast.parse(texts[0]), 'TAHAP')
    # Select key/title/date only; never evaluate tuple model references.
    catalog = {ast.literal_eval(k): (ast.literal_eval(v.elts[0]), ast.literal_eval(v.elts[2]))
               for k, v in zip(tahap.keys, tahap.values)}
    tree = ast.parse(texts[1])
    isi = _literal(_assignment(tree, 'ISI'))
    groups = _literal(_assignment(tree, 'KELOMPOK'))
    atur = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'atur')
    branch = next(n for n in atur.body if isinstance(n, ast.If)
                  and ast.unparse(n.test) == "kode == 'penyosohan'")
    sosoh = _literal(_assignment(branch, 'cols'), {'bahan_cols': [], 'hasil_cols': []})
    pins = {str(p.relative_to(ROOT)): sha256(s.encode()).hexdigest() for p, s in zip(paths, texts)}
    return catalog, isi, groups, sosoh, pins


def metadata(kode):
    """Fixed columns are native. Sosoh retains only genuinely invariant leaves."""
    catalog, isi, groups, sosoh, pins = _source()
    if kode not in catalog or kode == 'transfer_pk':
        raise ValueError('Report detail is outside this adapter.')
    if kode == 'penyosohan':
        columns = [dict(kunci=k, nama=n, kelompok={'bahan': 'Bahan', 'hasil': 'Hasil'}.get(k))
                   for k, n in sosoh]
    else:
        cols = [('kode', 'Kode')] + isi[kode]
        if kode not in ('gabah_masuk', 'pk_masuk', 'retur_pelanggan'):
            cols.append(('pemilik', 'Pemilik'))
        columns = [dict(kunci=k, nama=n, kelompok=groups.get(kode, {}).get(k)) for k, n in cols]
        if kode == 'penggilingan':
            for column in columns:
                if column['kunci'] in ('bahan_basah', 'bahan_kering', 'bahan'):
                    column['subkelompok'] = 'Gabah terpakai'
    from app.services.laporan_kepala import susun
    return dict(kode=kode, nama=catalog[kode][0], dasar=catalog[kode][1].replace('_', ' '),
                kolom=columns, kepala_tabel=susun(columns), dinamis=kode == 'penyosohan',
                source_pins=dict(pins))


def alamat(path, query=''):
    """Conservative adapter negotiation; unsupported queries keep native behavior."""
    if len(query) > 2048 or not path.startswith('/laporan/'):
        return None
    kode = path.removeprefix('/laporan/')
    if '/' in kode or kode not in _source()[0] or kode == 'transfer_pk':
        return None
    pairs = parse_qsl(query, keep_blank_values=True)
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys) or set(keys) - QUERY:
        return None
    return path + ('?' + query if query else '')


def memakai_dokumen(request):
    return (request.method == 'GET' and request.headers.get('X-Pindah') != '1'
            and alamat(request.url.path, request.url.query) is not None
            and (request.headers.get('X-Kerangka-Halaman') == '1'
                 or request.headers.get('Sec-Fetch-Mode') == 'navigate'
                 and request.headers.get('Sec-Fetch-Dest') in ('document', 'empty')))


def kontrak(request, akun, kode, periode='bulan_ini', dari=None, sampai=None):
    """Call with the SAME FastAPI-parsed arguments as detail_laporan, after auth.

    Order/error text repeats the existing native positive guards. This helper
    does not validate API/PDF requests or silently strengthen their contracts.
    """
    from fastapi import HTTPException
    from app.web.laporan import _daftar, boleh_lihat, PERIODE, _rentang
    lap = next((l for l in _daftar() if l.kode == 'tahap_' + kode), None)
    if lap is None:
        raise HTTPException(404, 'Laporan tidak dikenal.')
    if not boleh_lihat(akun.user, lap):
        raise HTTPException(403, 'Laporan ini tidak tersedia untuk peran Anda.')
    if periode not in {k for k, _ in PERIODE}:
        raise HTTPException(422, 'Periode tidak dikenal.')
    awal, akhir = _rentang(periode, dari, sampai)
    utama = ('penyosohan', 'penggilingan', 'pengeringan', 'transfer_pk')
    pilihan = sorted((l for l in _daftar() if boleh_lihat(akun.user, l)),
                     key=lambda l: utama.index(l.kode.removeprefix('tahap_'))
                     if l.kode.removeprefix('tahap_') in utama else len(utama))
    return dict(laporan=lap, tahap=kode, pilihan_laporan=[dict(kode=l.kode.removeprefix('tahap_'),
                nama=l.nama, kelompok='Proses' if l.kode.removeprefix('tahap_') in utama
                else 'Laporan lainnya') for l in pilihan], periode=PERIODE,
                periode_aktif=periode, dari=awal, sampai=akhir)


async def dokumen(request, akun, kode, periode='bulan_ini', dari=None, sampai=None):
    """UNWIRED: native handler invokes before ambil() with its parsed arguments."""
    if not memakai_dokumen(request) or request.url.path != '/laporan/' + kode:
        return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request) or getattr(request.state, 'portal_scope', None) is not None:
        return None
    # Do not call konteks_kerangka or inspect metadata before native authority.
    values = kontrak(request, akun, kode, periode, dari, sampai)
    from app.web.halaman_bertahap import konteks_kerangka, penanda_konteks
    from app.web.tampilan import render
    context = await konteks_kerangka(request, akun)
    target = alamat(request.url.path, request.url.query)
    response = render(request, 'laporan_detail_kerangka.html', **context, **values,
                      DETAIL_META=metadata(kode), DETAIL_URL=target,
                      DETAIL_STAMP=penanda_konteks(request, akun) + '|' + target,
                      layar='laporan', MENU_AKTIF='laporan', kembali='/laporan',
                      breadcrumb_induk=dict(nama='Laporan periode', alamat='/laporan'),
                      breadcrumb_detail=values['laporan'].nama)
    response.headers['Cache-Control'] = 'private, no-store'
    return response
