"""Compile final journey public structure; no app/models/database boot."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


def build():
    inputs = {Path(__file__).resolve(), ROOT / 'app/web/riwayat_pengiriman_catalog.py',
              ROOT / 'app/web/riwayat_pengiriman_kerangka.py', ROOT / 'app/web/layar_keluar.py',
              ROOT / 'app/web/templates/riwayat_kiriman.html', ROOT / 'hmu_tampilan/templates/_riwayat_kiriman.html',
              ROOT / 'app/web/templates/_status_timbang_pengiriman.html'}
    def module(name, path):
        inputs.add(path)
        spec = importlib.util.spec_from_file_location(name, path)
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    helper = module('journey_public_pool', ROOT / 'scripts/buat_kerangka_ui.py')
    breadcrumb = module('journey_native_breadcrumb', ROOT / 'app/web/breadcrumb.py')
    roots = [ROOT / 'app/web', ROOT / 'hmu_tampilan']
    env = Environment(loader=ChoiceLoader([helper.SourceLoader(p / 'templates', inputs) for p in roots]),
                      autoescape=True, undefined=StrictUndefined)
    base_path = ROOT / 'hmu_tampilan/templates/base.html'
    inputs.add(base_path)
    base = base_path.read_text()
    header_source = base[base.index('  {% if not kembali or LAPORAN_NAV %}'):base.index('  <span class="bar__merek"')]
    headers = {name: env.from_string(header_source).render(kembali=back, LAPORAN_NAV=None)
               for name, back in [('header_menu', None), ('header_back', '__PADI_HEADER_BACK__')]}
    crumb = BeautifulSoup(env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun(
        '/barang-keluar/1', dict(breadcrumb_detail='__PADI_CODE__', PENGIRIMAN_URL='/barang-keluar'),
        'Riwayat pengiriman · __PADI_CODE__')), 'html.parser')
    for a in crumb.select('a[href="/barang-keluar"]'):
        a['href'] = '__PADI_CHROME_BACK__'
    def asset(url):
        name = url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:
            raise ValueError('Only local static assets')
        path = next(p / 'static' / name for p in roots if (p / 'static' / name).is_file())
        inputs.add(path)
        return path.read_text()
    variants = {}
    for review in (False, True):
        # Public layout flags/placeholders only: no dummy ORM/actor/customer,
        # business row, weight/count, account, session or authorization decision.
        spec = dict(alamat='__PADI_DATA_URL__', stamp='__PADI_STAMP__', kembali='__PADI_BACK__',
                    meta=dict(kode='__PADI_CODE__', title='__PADI_TITLE__', status='selesai', bersama=True, review=review))
        template = env.get_template('riwayat_pengiriman_kerangka.html')
        raw = ''.join(template.blocks['isi'](template.new_context(dict(RP=spec, VERSI='__PADI_CAP__'))))
        doc = BeautifulSoup(raw, 'html.parser')
        if doc.select('form,input,select,textarea,[data-post],[data-kirim],[data-item],.rk-customer'):
            raise ValueError('Public final layout contains concrete record/action state')
        for node in doc.select('link[rel=stylesheet]'):
            css = asset(node['href'])
            if '@import' in css or '</style' in css.lower():
                raise ValueError('Native CSS needs review')
            style = doc.new_tag('style')
            style.string = helper.compact_css_comments(css)
            node.replace_with(style)
        for node in doc.select('script[src]'):
            js = asset(node['src'])
            if 'document.currentScript' in js:
                raise ValueError('Script binding needs review')
            node.attrs.clear()
            node.string = js.replace('</script', '<\\/script')
        variants['review' if review else 'read'] = dict(html=str(doc), breadcrumb=str(crumb), **headers)
    styles, scripts, srefs, jrefs = {}, {}, {}, {}
    for variant in variants.values():
        doc = BeautifulSoup(variant['html'], 'html.parser')
        for selector, pool, refs, attr in [('style', styles, srefs, 'data-rp-style'),
                                            ('script:not([type])', scripts, jrefs, 'data-rp-script')]:
            for node in doc.select(selector):
                node[attr] = helper.intern_text(pool, refs, node.string or '')
                node.clear()
        variant['html'] = str(doc)
    runtime_path = ROOT / 'app/web/static/kerangka-riwayat-pengiriman-ui-runtime.js'
    inputs.add(runtime_path)
    runtime = runtime_path.read_text()
    adapter = asset('/static/riwayat-pengiriman-native.js')
    start = adapter.index(' function address(value,origin){') + len(' function address(value,origin){')
    end = adapter.index('\n function holdActions(', start)
    body = adapter[start:end].strip().removesuffix('}').rstrip()
    marker = '/*__PADI_NATIVE_READ_ADDRESS__*/'
    if runtime.count(marker) != 1 or not body.endswith('return {u,id:Number(m[1])};'):
        raise ValueError('Native read allowlist changed')
    runtime = runtime.replace(marker, body)
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    data = dict(versi=1, sumber=source, variants=variants, styles=styles, scripts=scripts)
    payload = ('/* Public final journey structure, no business data. */\nwindow.PadiKerangkaRiwayatPengirimanData='
               + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n' + runtime).encode()
    if len(payload) > 524288:
        raise ValueError('Final journey package exceeds bound')
    meta = dict(versi=1, sumber=source, variants=list(variants),
                aset_sha256=hashlib.sha256(payload).hexdigest(), inputs=hashes)
    return payload, (json.dumps(meta, ensure_ascii=False, indent=2) + '\n').encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, payload in zip(('kerangka-riwayat-pengiriman-ui.js', 'kerangka-riwayat-pengiriman-ui.meta.json'), build()):
        path = ROOT / 'app/web/static' / name
        if args.check:
            if path.read_bytes() != payload:
                raise AssertionError('Final journey package stale: ' + name)
        else:
            path.write_bytes(payload)
        print(name, len(payload), 'bytes')


if __name__ == '__main__':
    main()
