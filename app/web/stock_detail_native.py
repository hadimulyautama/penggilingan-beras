"""Read-only deep Stock structure from already-authorized native presentation.

No stock reader, DTO substitute, arithmetic, permission or writer lives here.
Native callers retain their complete guards/reads before supplying real DTOs.
Direct documents therefore keep one complete native response; first-click
catalogs can expose structure before the next native document/data arrives.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ('pk-g1', 'pk-g2-curah', 'pk-g2-karung', 'product-auto', 'product-curah',
            'product-packed', 'warehouse-g1', 'warehouse-g2')
SELECTOR = ('a.stok-baris__tautan[href],a.stok-mobile-list__baris[href],'
            '.produk-list a.tabel-standar__baris[href],a.alur-gudang__buka[href]')


def address(value):
    if type(value) is not str or not value.startswith('/') or value.startswith('//') or len(value) > 4096:
        return None
    try:
        u = urlsplit(value)
        pairs = parse_qsl(u.query, keep_blank_values=True, max_num_fields=12)
    except ValueError:
        return None
    if u.scheme or u.netloc or u.fragment or len(dict(pairs)) != len(pairs):
        return None
    q = dict(pairs)
    if any(q.get(k) for k in ('buka', 'nilai', 'sumber_stok', 'tindakan')):
        return None
    if u.path == '/stok/pk/detail':
        if set(q) - {'gudang', 'kode', 'id', 'jasa', 'pemilik_id', 'gudang_filter', 'kembali_stok'} or q.get('gudang') not in ('g1', 'g2') or q.get('jasa', '0') not in ('0', '1'):
            return None
        owner = q.get('pemilik_id', '')
        if owner and owner != 'pabrik' and not (owner.isascii() and owner.isdigit() and int(owner) > 0):
            return None
        key = q.get('kode', '') if q['gudang'] == 'g1' else q.get('id', '')
        if not key or len(key) > 128 or q['gudang'] == 'g2' and not (key.isascii() and key.isdigit() and int(key) > 0):
            return None
        return dict(family='pk', identity=('pk', q['gudang'], key, q.get('jasa', '0'), owner), path=u.path)
    if u.path in ('/stok-produk/detail', '/stok-produk-jasa/detail'):
        if set(q) - {'jenis', 'pelanggan_id', 'sumber_page', 'kembali_stok'} or not 0 < len(q.get('jenis', '')) <= 128:
            return None
        jasa = u.path == '/stok-produk-jasa/detail'
        customer = q.get('pelanggan_id', '')
        if jasa and not (customer.isascii() and customer.isdigit() and int(customer) > 0) or not jasa and customer:
            return None
        page = q.get('sumber_page', '1')
        if not page.isascii() or not page.isdigit() or int(page) < 1:
            return None
        return dict(family='product', identity=('product', q['jenis'], customer), path=u.path)
    if u.path in ('/gudang/g1', '/gudang/g2') and not q:
        return dict(family='warehouse', identity=('warehouse', u.path.rsplit('/', 1)[1]), path=u.path)
    return None


@lru_cache(maxsize=1)
def automatic_kinds():
    # Presentation condition from the ACTUAL native detail template, not a
    # second Packing classification or a fixed grade/byproduct master.
    source = (ROOT/'hmu_tampilan/templates/stok_produk_detail.html').read_text()
    found = re.search(r'{% set otomatis = k\.jenis in (\([^\n]+\)) %}', source)
    if found is None:
        raise ValueError('Native product presentation switch requires review')
    result = ast.literal_eval(found[1])
    if not isinstance(result, tuple) or not all(type(v) is str for v in result):
        raise ValueError('Native presentation switch is not literal')
    return result


def metadata(variant, *, mutu=False, jasa=False, beras=False, qc_latest=None,
             stages=(), incoming='', stock=''):
    if variant not in VARIANTS or not all(type(v) is bool for v in (mutu, jasa, beras)) or qc_latest is not None and type(qc_latest) is not bool:
        return None
    if not isinstance(stages, (tuple, list)) or len(stages) > 8 or not all(type(s) is str and 0 < len(s) <= 128 for s in stages):
        return None
    if not all(type(v) is str and len(v) <= 256 for v in (incoming, stock)):
        return None
    return dict(variant=variant, mutu=mutu, jasa=jasa, beras=beras, qc_latest=qc_latest,
                stages=list(stages), incoming=incoming, stock=stock)


@dataclass(frozen=True)
class Offer:
    identity: tuple
    meta: dict
    title: str = field(default='', repr=False)
    leaf: str = field(default='', repr=False)


def pk_offers(lot, tempat, *, mutu):
    offers = []
    for warehouse, cards in (('g1', lot), ('g2', tempat)):
        for card in cards:
            key = card.kode if warehouse == 'g1' else str(card.intake_id)
            owner = ('pabrik' if card.jasa_id is None else str(card.jasa_id)) if card.bagian_pemilik else ''
            # Matches native card selection; G2 layout uses the actual DTO's
            # jumlah_karung, never a URL/role assumption or computed formula.
            variant = 'pk-g1' if warehouse == 'g1' else 'pk-g2-karung' if card.jumlah_karung else 'pk-g2-curah'
            offers.append(Offer(('pk', warehouse, key, '1' if card.jasa_id else '0', owner),
                                metadata(variant, mutu=mutu, jasa=bool(card.jasa_id)),
                                title='PK beli luar · '+card.kode if variant == 'pk-g2-karung' else 'Stok', leaf='Detail PK'))
    return offers


def product_offer(card, *, customer=None):
    from app.services.stok import adalah_beras
    variant = 'product-auto' if card.jenis in automatic_kinds() else 'product-curah' if card.curah_saja else 'product-packed'
    return Offer(('product', card.jenis, str(customer) if customer is not None else ''),
                 metadata(variant, jasa=customer is not None, beras=bool(adalah_beras(card.jenis))),
                 title='Detail '+card.nama, leaf=card.nama)


def product_offers(context):
    result = [product_offer(card) for card in context.get('kartu', ())]
    for customer in context.get('daftar', ()):
        result.extend(product_offer(card, customer=customer['pelanggan_id'])
                      for card in (*customer['beras'], *customer['samping']))
    if context.get('stok_jasa'):
        result.extend(product_offers(context['stok_jasa']))
    return result


def warehouse_offer(gid, actual_groups):
    group = next((g for g in actual_groups if g['id'] == gid and not g.get('terkunci')), None)
    if group is None or gid not in ('g1', 'g2'):
        return None
    return Offer(('warehouse', gid), metadata('warehouse-' + gid,
                 stages=[step['nama'] for step in group['langkah']],
                 incoming=group['masuk']['label'], stock=group['stok']['label']), title=group['nama'])


def finish(response, request, *, offers=(), detail=None):
    """Presentation decoration AFTER native guards, exact DTO selection/render.

    Never replace a paid-for full DTO/native document with another loading
    shell and repeat its reader. Direct/refresh responses stay complete and
    retain original controllers. Shells belong only to first-click factory.
    Actions/source/karung/portal remain entirely native.
    """
    if not offers and detail is None:
        return response
    from app.web.portal.scope import is_customer_read
    if (request.method != 'GET' or response.status_code != 200 or is_customer_read(request)
            or getattr(request.state, 'portal_scope', None) is not None
            or 'text/html' not in response.headers.get('content-type', '')):
        return response
    from bs4 import BeautifulSoup
    from app.web.stock_detail_catalog import catalog
    body = getattr(response, 'body', b'')
    if not body or len(body) > 8*1024*1024:
        return response
    doc = BeautifulSoup(body, 'html.parser')
    frame, session = doc.select_one('.bingkai'), doc.select_one('#formulir-sesi')
    cap = doc.html.get('data-versi', '') if doc.html else ''
    context = frame.get('data-pindah-konteks', '') if frame else ''
    token = session.get('data-token', '') if session else ''
    target = request.url.path + ('?' + request.url.query if request.url.query else '')
    if not all(type(v) is str and 0 < len(v) <= 512 for v in (cap, context, token)):
        return response
    def append_private(content, host):
        # Keep current-document catalogs in the same native content boundary:
        # AJAX/PADI native hydration extracts these markers, not the footer.
        marker = b'<!-- isi-halaman:akhir -->'
        if content.count(marker) == 1:
            return content.replace(marker, host+marker, 1)
        return content.replace(b'</body>', host+b'</body>', 1) if content.count(b'</body>') == 1 else content
    if detail is not None and address(target) is not None:
        # This private descriptor is NOT a first-click grant. Factory accepts
        # only the separate actual-visible-link catalog, not this self record.
        from jinja2.utils import htmlsafe_json_dumps
        data = dict(versi=1, cap=cap, konteks=context, sesi=token, alamat=target, metadata=detail)
        host = ('<script type="application/json" data-stock-detail-read>'+str(htmlsafe_json_dumps(data))+'</script>').encode()
        body = append_private(body, host)
    try:
        envelope = catalog(body.decode(), offers=offers, source_address=target,
                           cap=cap, context=context, session=token)
    except (ValueError, OSError):
        # An optional structure package mismatch must not discard a complete
        # already-authorized native page or replace it with false empty data.
        return response
    if envelope is not None and envelope['entries'] and body.count(b'</body>') == 1:
        from jinja2.utils import htmlsafe_json_dumps
        host = ('<script type="application/json" id="padi-stock-detail-catalog" data-cap="'+escape(cap, quote=True)
                +'" data-konteks="'+escape(context, quote=True)+'" data-source-address="'+escape(target, quote=True)
                +'">'+str(htmlsafe_json_dumps(envelope))+'</script>').encode()
        body = append_private(body, host)
    if body != response.body:
        response.body = body
        response.headers['Content-Length'] = str(len(body))
        response.headers['Cache-Control'] = 'private, no-store'
    return response


def structure(meta):
    """Literal native field/header labels; never call readers with empty rows."""
    variant = meta['variant']
    if variant == 'pk-g1':
        return dict(title='Detail PK', sections=[('Ringkasan stok', ['Letak', 'Hasil giling', 'Kemasan tersedia', 'Bahan masuk', 'Rendemen', 'Sudah dikirim', 'Status proses', 'Kondisi PK']), ('Batch gabah', ['Catatan asal', 'Bobot', 'Waktu'])], table=[])
    if variant == 'pk-g2-curah':
        return dict(title='Detail PK', sections=[('Ringkasan stok', ['Letak', 'Karung & curah tersedia', 'Berat awal masuk', 'Sudah dipindah ke silo', 'Kondisi PK'])], table=[])
    if variant == 'pk-g2-karung':
        return dict(title='Detail PK beli luar', sections=[('Surat jalan dan timbang', ['Karung & curah tersedia'])], table=[])
    if variant.startswith('product-'):
        auto = variant == 'product-auto'; curah = variant == 'product-curah'
        fields = ['Hasil sosoh · total', 'Sudah keluar', 'Dikemas otomatis' if auto else 'Tercatat' if curah else 'Dikemas', 'Curah · sisa kemasan' if auto else 'Belum dicatat' if curah else 'Belum dikemas · curah']
        if auto:
            fields.append('Kemasan otomatis')
        fields.append('Pemilik')
        return dict(title='Detail Stok Produk Jasa' if meta['jasa'] else 'Detail Stok Produk', sections=[('Ringkasan stok', fields), ('Asal stok dan produk kemasan', ['Perkiraan asal stok (FIFO)'])], table=['Bentuk stok / merek', 'Isi kemasan', 'Jumlah', 'Berat', 'Aksi'])
    return dict(title='Detail gudang', sections=[('Ringkasan gudang', []), ('Dryer / pengering', ['Jumlah alat', 'Terisi'])] if variant == 'warehouse-g1' else [('Ringkasan gudang', [])], table=[])
