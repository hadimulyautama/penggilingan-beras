"""Seven native history structures for this authenticated document only.

This is presentation, not a data/permission cache. Native GET repeats its own
authorization. No rows, totals, transaction defaults or identity options are
read here. Transfer, rice QC, detail and portal are outside this finite adapter.
"""
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request

MAX_JSON_BYTES = 1572864


def navigation(path, options):
    """Same native navigation metadata, with actual choices from pilihan()."""
    from app.web.laporan_navigasi import TAB, PROSES, QC
    from app.web.riwayat_daftar_metadata import PROCESS
    family = 'proses' if path in PROCESS else 'qc'
    kind = next((row[0] for row in options[family] if row[2] == path), None)
    return dict(aktif=family, judul='Riwayat proses' if family == 'proses' else 'Riwayat QC',
        jenis=kind, detail=False, panduan='rpd-panduan' if family == 'proses' else 'rqd-panduan',
        tab=[dict(kunci=key, nama=name, href=options[key][0][2] if options[key] else '',
                  boleh=bool(options[key]), alamat=[row[2] for row in options[key]])
             for key, name in TAB if key != 'laporan'],
        pilihan=list(PROSES if family == 'proses' else QC),
        boleh_alamat=[row[2] for row in options[family]])


@lru_cache(maxsize=16)
def _style(name):
    # Only immutable program text; never cache a document, actor or decision.
    roots = (Path(__file__).parent / 'static', Path(__file__).parents[2] / 'hmu_tampilan/static')
    source = next((root / name for root in roots if (root / name).is_file()), None)
    if source is None:
        raise ValueError('Native history stylesheet unavailable')
    text = source.read_text()
    if '@import' in text or '</style' in text.lower():
        raise ValueError('History stylesheet needs an explicit source review')
    return text


def inline_styles(html, cap):
    from bs4 import BeautifulSoup
    doc = BeautifulSoup(html, 'html.parser')
    allowed = {'riwayat.css', 'riwayat-sosoh-desain.css', 'riwayat-giling-daftar.css',
               'riwayat-daftar-proses.css', 'riwayat-qc-desain.css',
               'laporan-riwayat.css', 'laporan-kontrol.css'}
    main = doc.select_one('#isi-halaman')
    for link in main.select('link[rel=stylesheet][href]'):
        target = urlsplit(link['href'])
        if target.path.removeprefix('/static/') not in allowed:
            continue  # Other native shared styles retain their original load.
        if target.scheme or target.netloc or not target.path.startswith('/static/'):
            raise ValueError('Native style must be local')
        from urllib.parse import parse_qs
        if parse_qs(target.query).get('v') != [cap]:
            raise ValueError('Native history style version mismatch')
        style = doc.new_tag('style', attrs={'data-history-native-style': target.path})
        style.string = _style(target.path.removeprefix('/static/'))
        link.replace_with(style)
    return str(doc)  # BeautifulSoup already preserves an existing native doctype.


def valid(data):
    from jinja2.utils import htmlsafe_json_dumps
    from app.web.riwayat_daftar_metadata import PROCESS, QC
    allowed = set(PROCESS) | {'/riwayat-qc/' + key for key in QC}
    if (not isinstance(data, dict)
            or set(data) != {'versi', 'cap', 'konteks', 'sesi', 'penyandian', 'potongan', 'frames'}
            or data['versi'] != 1 or data['penyandian'] != 'baris-1'
            or not all(isinstance(data[key], str) and data[key] for key in ('cap', 'konteks', 'sesi'))):
        return False
    frames, parts = data['frames'], data['potongan']
    if (not isinstance(frames, dict) or not frames or not set(frames) <= allowed
            or not isinstance(parts, list) or not 0 < len(parts) <= 16384
            or not all(isinstance(part, str) and part for part in parts)):
        return False
    for refs in frames.values():
        if (not isinstance(refs, list) or not 0 < len(refs) <= 16384
                or not all(type(n) is int and 0 <= n < len(parts) for n in refs)
                or sum(len(parts[n].encode()) for n in refs) > 524288):
            return False
    return len(htmlsafe_json_dumps(data).encode()) <= MAX_JSON_BYTES


async def susun(request, akun, *, navigasi, registry):
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request) or getattr(request.state, 'portal_scope', None) is not None:
        return None
    from app.web.laporan_navigasi import pilihan
    from app.web.riwayat_daftar_metadata import PROCESS, QC
    from app.web.riwayat_daftar_bertahap import _boleh, kerangka
    from app.web.kerangka_langsung import kemas_frame
    options = await pilihan(akun)
    state = dict(request.scope.get('state', {}))
    state.update(menyusun_kerangka_langsung=True, frame_kerangka_langsung=True)
    frames = {}
    for path in (*PROCESS, *('/riwayat-qc/' + key for key in sorted(QC))):
        if not await _boleh(akun.user, path):
            continue
        native = Request({**request.scope, 'path': path, 'raw_path': path.encode(),
                          'query_string': b'', 'state': dict(state)})
        context = {**navigasi, 'LAPORAN_NAV': navigation(path, options),
                   'MENU_AKTIF': 'laporan_riwayat'}
        response = await kerangka(native, akun, context)
        if response is None or response.status_code != 200:
            continue
        html = inline_styles(response.body.decode(), registry['cap'])
        if len(html.encode()) > 524288:
            return None
        frames[path] = html
    if not frames:
        return None
    result = dict(versi=1, cap=registry['cap'], konteks=registry['konteks'],
                  sesi=registry['sesi'], **kemas_frame(frames))
    return result if valid(result) else None
