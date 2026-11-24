"""Struktur detail riwayat/QC; angka, rumus dan koreksi tetap native.

Pilihan bentuk bukan izin. Factory hanya berjalan sesudah dependency dan
guard caller asli; gate resource minimum mengulang predicate pembaca native.
Tidak membangun DTO kosong yang akan menampilkan rata-rata atau stok nol.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl

from jinja2 import Environment, nodes

ROOT = Path(__file__).resolve().parents[2]
QC = ('gabah-basah', 'gabah-kering', 'pk-luar', 'pk-hasil-giling', 'beras-hasil-sosoh')
PROSES = ('giling', 'sosoh', 'pengeringan')
VARIANTS = (*('riwayat-' + x for x in PROSES), *('qc-' + x for x in QC), 'qc-beras-daftar')
_ID = re.compile(r'/riwayat-(giling|sosoh|pengeringan)/([1-9][0-9]{0,9})')
_QC = re.compile(r'/riwayat-qc/(' + '|'.join(QC) + r')(?:/([A-Za-z0-9][A-Za-z0-9._-]{0,79}))?')
KEMBALI_QC = ('kembali_qc', 'kembali_jasa', 'kembali_stok', 'kembali_kerja')


def deskripsi(path, query=''):
    if type(path) is not str or type(query) is not str or len(query) > 3000 or re.search(r'%(?![0-9a-fA-F]{2})', query):
        return None
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=10, errors='strict')
    except (ValueError, UnicodeError):
        return None
    q = dict(pairs)
    if len(q) != len(pairs):
        return None
    history, qc = _ID.fullmatch(path), _QC.fullmatch(path)
    if history:
        kind, identifier = history.groups()
        if int(identifier) > 2147483647:
            return None
        allowed = {'tab_detail', 'halaman_jeda'}
        if kind == 'giling':
            allowed.add('sebelum')
        if kind == 'pengeringan':
            allowed.update(('halaman_ukur', 'halaman_dingin', 'kembali_kerja'))
        if set(q) - allowed:
            return None
        variant = 'riwayat-' + kind
        selected = q.get('tab_detail')
        if selected not in dict(metadata(variant)['tabs']):
            selected = ('pengukuran' if kind == 'pengeringan' and q.get('halaman_ukur')
                        else 'riwayat' if kind == 'pengeringan' and (q.get('halaman_dingin') or q.get('halaman_jeda'))
                        else 'ringkasan')
        # Cursor invalid tetap ditangani native; jangan mengubah aturan query.
        if 'sebelum' in q and q['sebelum'] and not re.fullmatch(r'-?[0-9]{1,10}', q['sebelum']):
            return None
        reference = None
    elif qc:
        kind, reference = qc.groups()
        identifier = None
        if reference is None:
            if kind != 'beras-hasil-sosoh' or query:
                return None  # Empat daftar lain sudah mempunyai adopter sendiri.
            variant, selected = 'qc-beras-daftar', None
        else:
            allowed = {'tab_qc'} | (set(KEMBALI_QC) | {'putaran'} if kind != 'beras-hasil-sosoh' else set())
            if set(q) - allowed:
                return None
            variant = 'qc-' + kind
            selected = q.get('tab_qc')
            if selected not in dict(metadata(variant)['tabs']):
                selected = 'ringkasan'
            if q.get('putaran') and not re.fullmatch(r'[1-9][0-9]{0,8}', q['putaran']):
                return None
    else:
        return None
    if any(key.startswith('halaman_') and not re.fullmatch(r'[1-9][0-9]{0,8}', value) for key, value in q.items()):
        return None
    address = path + ('?' + query if query else '')
    return dict(variant=variant, jenis=kind, id=int(identifier) if identifier else None,
                referensi=reference, tab=selected, alamat=address, data_url=address)


def _tabs(text, expected):
    for node in Environment().parse(text).find_all(nodes.For):
        if not isinstance(node.iter, nodes.List):
            continue
        pairs = []
        for entry in node.iter.items:
            if (not isinstance(entry, nodes.Tuple) or len(entry.items) != 2
                    or not all(isinstance(x, nodes.Const) and type(x.value) is str for x in entry.items)):
                break
            pairs.append(tuple(x.value for x in entry.items))
        else:
            if tuple(x[0] for x in pairs) == expected:
                return pairs
    raise ValueError('Urutan tab native berubah; perlu ditinjau')


@lru_cache(maxsize=16)
def metadata(variant):
    from bs4 import BeautifulSoup
    if variant not in VARIANTS:
        raise ValueError('Bentuk detail tidak dikenal')
    paths = [ROOT / 'app/web/layar_riwayat.py']
    extra_tables = {}
    tree = ast.parse(paths[0].read_text())
    pages = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'QC_PAGES' for t in node.targets))
    if variant.startswith('riwayat-'):
        kind = variant.removeprefix('riwayat-')
        template = {'giling': 'riwayat_giling_detail.html', 'sosoh': 'riwayat_sosoh_detail.html',
                    'pengeringan': 'riwayat_pengeringan_detail.html'}[kind]
        paths.append(ROOT / 'app/web/templates' / template)
        text = paths[-1].read_text()
        title = re.search(r'<h1>([^<{]+)</h1>', text)
        if not title:
            raise ValueError('Judul riwayat native berubah')
        tabs = _tabs(text, ('ringkasan', 'bahan', 'pengukuran', 'riwayat') if kind == 'pengeringan'
                     else ('ringkasan', 'bahan', 'hasil', 'qc', 'riwayat'))
        titles = [n.get_text() for n in BeautifulSoup(text, 'html.parser').select('h2')
                  if not any(x in str(n) for x in ('{{', '{%'))]
        tables = []
        for head in BeautifulSoup(text, 'html.parser').select('.riwayat-detail__table-head'):
            labels = [n.get_text() for n in head.select('span')]
            if labels and not any('{' in x for x in labels):
                tables.append(labels)
        family, title = 'riwayat', title[1]
        if kind == 'pengeringan':
            paths.append(ROOT / 'app/services/proses_aktif.py')
            wanted = {'Asal bahan gabah', 'Riwayat pengukuran kadar air', 'Catatan pendinginan'}
            for node in ast.walk(ast.parse(paths[-1].read_text())):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id not in {'_bagian', '_log'}:
                    continue
                for i, arg in enumerate(node.args[:-1]):
                    if isinstance(arg, ast.Constant) and arg.value in wanted:
                        columns = ast.literal_eval(node.args[i + 1])
                        if not isinstance(columns, list) or not all(type(v) is str for v in columns):
                            raise ValueError('Kolom pengeringan native berubah')
                        extra_tables[arg.value] = columns
            if set(extra_tables) != wanted:
                raise ValueError('Bagian pengeringan native berubah')
    else:
        rice = variant in ('qc-beras-hasil-sosoh', 'qc-beras-daftar')
        template = 'qc_sosoh_riwayat.html' if rice else 'riwayat_qc_detail.html'
        paths.append(ROOT / 'app/web/templates' / template)
        text = paths[-1].read_text()
        tabs = [] if variant == 'qc-beras-daftar' else _tabs(text, ('ringkasan', 'sampel', 'sesi', 'asal')
                    if rice else ('ringkasan', 'putaran', 'perhitungan', 'asal'))
        kind = 'beras-hasil-sosoh' if rice else variant.removeprefix('qc-')
        title = 'Riwayat QC beras hasil sosoh' if rice else pages[kind][0]
        tables = []
        titles = [n.get_text() for n in BeautifulSoup(text, 'html.parser').select('h2')
                  if not any(x in str(n) for x in ('{{', '{%'))]
        if rice:
            paths.append(ROOT / 'app/web/templates/_qc_sosoh.html')
            part = BeautifulSoup(paths[-1].read_text(), 'html.parser')
            for table in part.select('table'):
                columns = [n.get_text() for n in table.select('thead th')]
                if not columns or any('{' in x for x in columns):
                    raise ValueError('Kolom QC beras native berubah')
                tables.append(columns)
        family = 'qc'
    return dict(variant=variant, family=family, title=title, tabs=tabs,
                native_titles=list(dict.fromkeys(titles)), tables=tables, extra_tables=extra_tables,
                inputs={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def memakai_dokumen(request):
    return (request.method == 'GET' and request.headers.get('X-Pindah') != '1'
            and not getattr(request.state, 'isi_halaman_bertahap', False)
            and (request.headers.get('X-Kerangka-Halaman') == '1'
                 or request.headers.get('Sec-Fetch-Mode') == 'navigate'
                 and request.headers.get('Sec-Fetch-Dest') in {'document', 'empty'}))


async def _sumber(db, user, spec):
    """Predicate minimum sama dengan WHERE pembaca native; bukan DTO/domain math."""
    from sqlalchemy import exists, select
    from app.services.cakupan_fasilitas import batas
    from app.models import (DryingLot, MillingProcess, MillingQcLog, PkPurchaseBatch,
                            PkPurchaseQcLog, PolishingProcess, PurchaseBatch,
                            PurchaseBatchQc, PurchaseBatchQcSample, SampelQcSosoh)
    if spec['variant'].startswith('riwayat-'):
        model = {'giling': MillingProcess, 'sosoh': PolishingProcess, 'pengeringan': DryingLot}[spec['jenis']]
        code = model.kode_lot if spec['jenis'] == 'pengeringan' else model.kode_proses
        completed = model.waktu_selesai_pendinginan.is_not(None) if spec['jenis'] == 'pengeringan' else model.status == 'selesai'
        return await db.scalar(select(code).where(model.id == spec['id'], batas(user, model), completed).limit(1))
    kind, reference = spec['jenis'], spec['referensi']
    if spec['variant'] == 'qc-beras-daftar':
        return ''  # Pintu daftar sudah digate per jenis; kosong bukan hasil query.
    if kind in ('gabah-basah', 'gabah-kering'):
        return await db.scalar(select(PurchaseBatch.kode_batch)
            .join(PurchaseBatchQc, PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
            .join(PurchaseBatchQcSample, PurchaseBatchQcSample.purchase_batch_qc_id == PurchaseBatchQc.id)
            .where(batas(user, PurchaseBatch), PurchaseBatch.kode_batch == reference,
                   PurchaseBatch.kondisi_gabah == ('basah' if kind == 'gabah-basah' else 'kering'),
                   PurchaseBatch.dibatalkan_pada.is_(None)).limit(1))
    if kind == 'pk-luar':
        return await db.scalar(select(PkPurchaseBatch.kode_batch)
            .join(PkPurchaseQcLog, PkPurchaseQcLog.pk_purchase_batch_id == PkPurchaseBatch.id)
            .where(batas(user, PkPurchaseBatch), PkPurchaseBatch.kode_batch == reference).limit(1))
    if kind == 'pk-hasil-giling':
        return await db.scalar(select(MillingProcess.kode_proses)
            .join(MillingQcLog, MillingQcLog.milling_process_id == MillingProcess.id)
            .where(batas(user, MillingProcess), MillingProcess.kode_proses == reference).limit(1))
    # Sampel dibatalkan tetap ada dalam data_proses.sampel. Jangan menyaringnya
    # seakan tidak pernah dicatat, atau menganggap output log sebagai QC.
    return await db.scalar(select(PolishingProcess.kode_proses).where(
        batas(user, PolishingProcess), PolishingProcess.kode_proses == reference,
        exists().where(SampelQcSosoh.polishing_process_id == PolishingProcess.id)).limit(1))


async def kerangka(request, akun):
    if not memakai_dokumen(request):
        return None
    from app.web.portal.scope import is_customer_read
    if (akun is None or getattr(request.state, 'akun', None) is not akun
            or is_customer_read(request) or getattr(request.state, 'portal_scope', None) is not None
            or getattr(akun, 'harus_ganti_sandi', None) is not False
            or getattr(request.state, 'koreksi_gagal', None) or getattr(request.state, 'koreksi_form', None)):
        return None
    try:
        spec = deskripsi(request.url.path, request.url.query)
        shape = metadata(spec['variant']) if spec is not None else None
    except (ValueError, SyntaxError, StopIteration, OSError):
        # Perubahan struktur program membuat adapter menolak. Native data
        # reader/POST tidak boleh ikut gagal karena bentuk opsional ini.
        return None
    if spec is None:
        return None
    from app.web.api import _is_gabah_operator, _is_g2_operator, _is_jenis_operator
    kind = spec['jenis']
    allowed = await (_is_gabah_operator(akun.user) if kind in ('gabah-basah', 'gabah-kering')
                     else _is_g2_operator(akun.user) if kind == 'pk-luar'
                     else _is_jenis_operator(akun.user, {'giling': 'penggilingan', 'pk-hasil-giling': 'penggilingan',
                         'sosoh': 'penyosohan', 'beras-hasil-sosoh': 'penyosohan', 'pengeringan': 'pengeringan'}[kind]))
    if not allowed:
        return None  # Caller asli tetap pemilik status/pesan penolakan.
    from app.database import SessionLocal
    async with SessionLocal() as db:
        code = await _sumber(db, akun.user, spec)
    if code is None:
        return None  # Missing resource asli tetap404/redirect, bukan shell sukses.
    from app.web.halaman_bertahap import konteks_kerangka, penanda_konteks
    from app.web.laporan_navigasi import siapkan
    from app.web.tampilan import render
    values = await konteks_kerangka(request, akun)
    await siapkan(request, values)
    if values.get('LAPORAN_NAV'):
        values['LAPORAN_NAV'] = {**values['LAPORAN_NAV'], 'panduan': 'rdn-panduan'}
    spec.update(meta=shape, kode=code,
                stamp=penanda_konteks(request, akun) + '|' + spec['alamat'],
                boleh_koreksi=bool(akun.is_admin and kind in ('giling', 'sosoh')),
                boleh_qc=bool(akun.is_admin and values.get('MUTU_AKTIF') is True
                              and spec['variant'] == 'qc-beras-daftar'))
    parent = '/riwayat-' + kind if spec['variant'].startswith('riwayat-') else '/riwayat-qc/' + kind
    if spec['variant'] == 'riwayat-giling':
        from app.web.layar_riwayat import _query_giling
        parent += _query_giling(request) + '#giling-' + str(spec['id'])
    elif spec['variant'] == 'riwayat-pengeringan':
        from app.web.layar_pekerjaan import konteks_aman
        parent = konteks_aman(request.query_params.get('kembali_kerja')) or parent
    elif spec['variant'].startswith('qc-') and kind != 'beras-hasil-sosoh':
        # Sama dengan bagian navigasi detail_qc.konteks, tanpa membuat kartu
        # kosong demi menghitung putaran/catatan yang belum dibaca.
        from urllib.parse import urlsplit
        from app.web.detail_qc import ASAL
        for key in KEMBALI_QC:
            value = request.query_params.get(key, '')
            try:
                target = urlsplit(value)
            except ValueError:
                continue
            if not target.scheme and not target.netloc and re.fullmatch(ASAL, target.path):
                parent = value
                break
        else:
            try:
                target = urlsplit(request.headers.get('referer', ''))
            except ValueError:
                target = None
            if target and target.netloc == request.url.netloc and re.fullmatch(ASAL, target.path):
                parent = target.path + ('?' + target.query if target.query else '')
    template = ('riwayat_detail_native.html' if spec['variant'].startswith('riwayat-') else
                'qc_beras_native.html' if kind == 'beras-hasil-sosoh' else 'qc_detail_native.html')
    response = render(request, template, **{**values, 'DETAIL_RIWAYAT': spec,
        'kembali': parent, 'layar': 'laporan_riwayat', 'breadcrumb_detail': code or spec['meta']['title']})
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    # Tombol Cetak di bilah native juga tidak boleh mencetak placeholder.
    response.body = re.sub(rb'<button\b[^>]*\bdata-lk-cetak\b[^>]*>',
        lambda m: m[0] if re.search(rb'\bdisabled(?:\s|=|>)', m[0]) else
        m[0][:-1] + b' disabled aria-describedby="rdn-menunggu">', response.body)
    response.headers['content-length'] = str(len(response.body))
    return response


@lru_cache(maxsize=1)
def aset():
    folder = ROOT / 'app/web/static'
    value = json.loads((folder / 'kerangka-riwayat-detail-ui.meta.json').read_text())
    if (value.get('versi') != 1 or value.get('variants') != list(VARIANTS)
            or hashlib.sha256((folder / 'kerangka-riwayat-detail-ui.js').read_bytes()).hexdigest() != value.get('aset_sha256')):
        raise ValueError('Paket detail riwayat/QC tidak cocok')
    return value
