"""Paket publik detail dari source label/template native; tanpa app/DB/DTO."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ('kerangka-riwayat-detail-ui.js', 'kerangka-riwayat-detail-ui.meta.json')


def build():
    inputs = {Path(__file__).resolve(), ROOT / 'app/web/static/kerangka-riwayat-detail-ui-runtime.js'}

    def module(name, path):
        inputs.add(path)
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value

    native = module('detail_native_metadata', ROOT / 'app/web/riwayat_detail_native.py')
    helper = module('public_native_program', ROOT / 'scripts/buat_kerangka_ui.py')
    navigation = module('public_native_history_navigation', ROOT / 'scripts/buat_kerangka_riwayat.py')
    breadcrumb = module('public_detail_breadcrumb', ROOT / 'app/web/breadcrumb.py')
    inputs.add(ROOT / 'app/web/laporan_navigasi.py')
    chrome = module('detail_chrome_source', ROOT / 'app/web/native_detail_chrome.py')
    base_path = ROOT / 'hmu_tampilan/templates/base.html'
    inputs.add(base_path)
    bar_control = chrome.kontrol_bar(base_path.read_text(), laporan=True)
    literals = navigation.native_navigation_literals()
    roots = [ROOT / 'app/web', ROOT / 'hmu_tampilan']

    class SourceLoader(FileSystemLoader):
        def get_source(self, env, name):
            value = super().get_source(env, name)
            inputs.add(Path(value[1]))
            return value

    env = Environment(loader=ChoiceLoader([SourceLoader(str(r / 'templates')) for r in roots]),
                      undefined=StrictUndefined, autoescape=True)

    def asset(address, seen=()):
        url = urlsplit(address)
        name = url.path.removeprefix('/static/')
        if url.scheme or url.netloc or not url.path.startswith('/static/') or not name or '/' in name or '\\' in name or name in seen or len(seen) > 8:
            raise ValueError('Hanya aset program native lokal')
        path = next(r / 'static' / name for r in roots if (r / 'static' / name).is_file())
        inputs.add(path)
        text = path.read_text()
        if name.endswith('.css'):
            text = re.sub(r"@import\s+url\(['\"](/static/[^'\"]+)['\"]\);", lambda m: asset(m[1], (*seen, name)), text)
            if '@import' in text or '</style' in text.lower():
                raise ValueError('Gaya native membutuhkan review')
            text = helper.compact_css_comments(text)
        return text

    variants = {}
    for variant in native.VARIANTS:
        meta = native.metadata(variant)
        inputs.update(ROOT / path for path in meta['inputs'])
        kind = variant.removeprefix('riwayat-') if variant.startswith('riwayat-') else variant.removeprefix('qc-')
        if variant == 'qc-beras-daftar':
            address, kind = '/riwayat-qc/beras-hasil-sosoh', 'beras-hasil-sosoh'
        else:
            address = '/riwayat-' + kind + '/1' if variant.startswith('riwayat-') else '/riwayat-qc/' + kind + '/PADI-KODE'
        parent = '/riwayat-' + kind if variant.startswith('riwayat-') else '/riwayat-qc/' + kind
        if variant == 'riwayat-giling':
            parent += '#giling-1'
        value = native.deskripsi(address)
        value.update(meta=meta, kode='PADI-KODE', stamp='__PADI_STAMP__', boleh_koreksi=True, boleh_qc=True,
                     back_html=native.back_html(meta, parent, kind))
        template = ('riwayat_detail_native.html' if variant.startswith('riwayat-') else
                    'qc_beras_native.html' if kind == 'beras-hasil-sosoh' else 'qc_detail_native.html')
        t = env.get_template(template)
        body = ''.join(t.blocks['isi'](t.new_context(dict(DETAIL_RIWAYAT=value, VERSI='__PADI_CAP__', kembali='/riwayat', PORTAL_READ_ONLY=False))))
        family = 'proses' if variant.startswith('riwayat-') else 'qc'
        nav_meta = dict(family=family, kind=kind)
        nav = navigation.public_navigation('/riwayat-' + kind, nav_meta, literals)
        nav.update(detail=variant != 'qc-beras-daftar', panduan='rdn-panduan')
        context = dict(KATALOG_NATIVE=body, VERSI='__PADI_CAP__', LAPORAN_NAV=nav,
                       PORTAL_READ_ONLY=False, TAMPILAN_INDUK=True)
        wrapper = env.get_template('laporan_katalog_blueprint.html').render(**context)
        doc = BeautifulSoup(wrapper, 'html.parser')
        back_context = doc.new_tag('template')
        back_context['data-rdn-back-context'] = ''
        back_context.append(BeautifulSoup(native.back_html(meta, '/pekerjaan', kind, '/pekerjaan'), 'html.parser'))
        doc.select_one('[data-riwayat-detail-native]').append(back_context)
        # The public program carries no authority. The factory enables only
        # native read-navigation selectors after validating the private menu.
        for node in doc.select('select[data-jenis-riwayat]'):
            node['disabled'] = ''
        if doc.select('form,[name],[data-post],[data-kirim]') or any(not n.has_attr('disabled') or n.has_attr('value') for n in doc.select('input,textarea')):
            raise ValueError('Bentuk detail publik tidak boleh memuat field tulis aktif')
        for node in doc.select('[data-lk-cetak]'):
            node['disabled'] = ''
            node['aria-describedby'] = 'rdn-menunggu'
        for node in doc.select('link[rel=stylesheet]'):
            style = doc.new_tag('style')
            style.string = asset(node['href'])
            node.replace_with(style)
        for node in doc.select('script[src]'):
            code = asset(node['src'])
            if 'document.currentScript' in code:
                raise ValueError('Binding program native memerlukan review')
            node.attrs.clear()
            node.string = code.replace('</script', '<\\/script')
        program = doc.new_tag('script')
        program.string = asset('/static/riwayat-navigasi-native.js').replace('</script', '<\\/script')
        doc.append(program)
        crumb = env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun(
            address, dict(kembali=parent, breadcrumb_detail='PADI-KODE'), meta['title']))
        variants[variant] = dict(title_parts=meta['document_parts'], bar_control=bar_control, html=str(doc), breadcrumb=crumb)
    styles, scripts, sr, jr = {}, {}, {}, {}
    for value in variants.values():
        doc = BeautifulSoup(value['html'], 'html.parser')
        for selector, pool, refs, attr in [('style', styles, sr, 'data-detail-style'), ('script:not([type])', scripts, jr, 'data-detail-script')]:
            for node in doc.select(selector):
                node[attr] = helper.intern_text(pool, refs, node.string or '')
                node.clear()
        value['html'] = str(doc)
        if len(value['html'].encode()) > 262144:
            raise ValueError('Bentuk detail melewati batas')
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    data = dict(versi=1, sumber=digest, variants=variants, styles=styles, scripts=scripts)
    payload = ('/* Struktur detail publik, tanpa catatan, akun atau nilai transaksi. */\nwindow.PadiKerangkaRiwayatDetailData=' +
               json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n' +
               (ROOT / 'app/web/static/kerangka-riwayat-detail-ui-runtime.js').read_text()).encode()
    if len(payload) > 800000:
        raise ValueError('Paket detail melampaui batas')
    meta = dict(versi=1, sumber=digest, variants=list(native.VARIANTS),
                aset_sha256=hashlib.sha256(payload).hexdigest(), inputs=hashes)
    return payload, (json.dumps(meta, ensure_ascii=False, indent=2) + '\n').encode()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    options = parser.parse_args()
    for name, payload in zip(OUTPUTS, build()):
        path = ROOT / 'app/web/static' / name
        if options.check:
            if path.read_bytes() != payload:
                raise AssertionError('Paket detail basi: ' + name)
        else:
            path.write_bytes(payload)
        print(name, len(payload))
