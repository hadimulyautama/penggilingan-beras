"""Public viewer structure from the three original native HTML templates only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


def build():
    inputs = {Path(__file__).resolve(), ROOT / 'app/web/proses_pdf_kerangka.py',
              ROOT / 'app/web/proses_pdf_catalog.py', ROOT / 'app/web/layar_riwayat.py',
              ROOT / 'app/web/layar_sosoh.py', ROOT / 'hmu_tampilan/templates/_laporan_navigasi.html',
              ROOT / 'hmu_tampilan/static/laporan-kontrol.js'}
    def module(name, path):
        inputs.add(path)
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value
    helper = module('viewer_public_pool', ROOT / 'scripts/buat_kerangka_ui.py')
    breadcrumb = module('viewer_native_breadcrumb', ROOT / 'app/web/breadcrumb.py')
    roots = [ROOT / 'app/web', ROOT / 'hmu_tampilan']
    env = Environment(loader=ChoiceLoader([helper.SourceLoader(p / 'templates', inputs) for p in roots]),
                      autoescape=True, undefined=StrictUndefined)
    base_path = ROOT / 'hmu_tampilan/templates/base.html'
    inputs.add(base_path)
    base = base_path.read_text()
    header_source = base[base.index('  {% if not kembali or LAPORAN_NAV %}'):base.index('  <span class="bar__merek"')]
    header = env.from_string(header_source).render(kembali=None, LAPORAN_NAV=True)
    def asset(url):
        name = url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:
            raise ValueError('Local program assets only')
        path = next(p / 'static' / name for p in roots if (p / 'static' / name).is_file())
        inputs.add(path)
        return path.read_text()
    variants = {}
    for kind in ('giling', 'sosoh', 'pengeringan'):
        native = env.get_template('laporan_' + kind + '.html')
        raw = ''.join(native.blocks['isi'](native.new_context(dict(kode='__PADI_CODE__', pdf_url='__PADI_PDF_URL__'))))
        doc = BeautifulSoup(raw, 'html.parser')
        frames = doc.select('iframe')
        shares = doc.select('#bagikan-pdf')
        downloads = doc.select('a[href="__PADI_PDF_URL__?unduh=1"]')
        if (len(frames), len(shares), len(downloads)) != (1, 1, 1) or not shares[0].has_attr('disabled'):
            raise ValueError('Native viewer controls changed')
        frames[0].attrs.pop('src')
        frames[0]['data-ppv-title'] = ''
        frames[0]['aria-busy'] = 'true'
        doc.select_one('h2')['data-ppv-heading'] = ''
        downloads[0].attrs.pop('href')
        downloads[0]['aria-disabled'] = 'true'
        downloads[0]['role'] = 'link'
        downloads[0]['tabindex'] = '-1'
        downloads[0]['aria-describedby'] = 'status-bagikan'
        downloads[0]['data-ppv-download'] = ''
        doc.select_one('#status-bagikan').string = 'Menyiapkan halaman laporan…'
        # The original share-fetch program runs only in ORIGINAL fresh HTML,
        # never in the public pending structure. No binary request is added.
        for script in doc.select('script'):
            script.decompose()
        wrapper = env.get_template('proses_pdf_kerangka.html').render(
            VIEWER_NATIVE=str(doc), data_url='__PADI_DATA_URL__', stamp='__PADI_STAMP__', VERSI='__PADI_CAP__')
        part = BeautifulSoup(wrapper, 'html.parser')
        if part.select('form,input,select,textarea,[data-post],[data-kirim],iframe[src],iframe[srcdoc]'):
            raise ValueError('Public viewer includes a data/action request')
        for node in part.select('script[src]'):
            js = asset(node['src'])
            if 'document.currentScript' in js:
                raise ValueError('Script binding needs review')
            node.attrs.clear()
            node.string = js.replace('</script', '<\\/script')
        # Match native PDF context exactly: kode alone does not set the parent
        # breadcrumb_detail, so the native intermediate label is Detail proses.
        crumb = BeautifulSoup(env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun(
            '/riwayat-' + kind + '/1/laporan', dict(kode='__PADI_CODE__'), 'Laporan __PADI_CODE__')), 'html.parser')
        for a in crumb.select('a[href="/riwayat-' + kind + '/1"]'):
            a['href'] = '__PADI_DETAIL__'
        variants[kind] = dict(html=str(part), breadcrumb=str(crumb), header=header,
                              heading_parts=doc.select_one('h2').get_text().split('__PADI_CODE__'),
                              iframe_parts=frames[0]['title'].split('__PADI_CODE__'))
    styles, scripts, srefs, jrefs = {}, {}, {}, {}
    for variant in variants.values():
        part = BeautifulSoup(variant['html'], 'html.parser')
        for selector, pool, refs, attr in [('style', styles, srefs, 'data-ppv-style'),
                                          ('script:not([type])', scripts, jrefs, 'data-ppv-script')]:
            for node in part.select(selector):
                node[attr] = helper.intern_text(pool, refs, node.string or '')
                node.clear()
        variant['html'] = str(part)
    # Keep the actual current native control DOM/allowed choices. Rebind only
    # its pinned native CSS/controller, because hydrated DOM nodes have had
    # src/href replaced by inline program text and carry data-siap markers.
    navigation = dict(styles=[], script=None)
    for name in ('laporan-riwayat.css', 'laporan-kontrol.css'):
        css = asset('/static/' + name)
        if '@import' in css or '</style' in css.lower():
            raise ValueError('Native navigation CSS needs review')
        navigation['styles'].append(helper.intern_text(styles, srefs, helper.compact_css_comments(css)))
    navigation['script'] = helper.intern_text(scripts, jrefs, asset('/static/laporan-kontrol.js'))
    runtime_path = ROOT / 'app/web/static/kerangka-proses-pdf-ui-runtime.js'
    inputs.add(runtime_path)
    runtime = runtime_path.read_text()
    adapter = asset('/static/proses-pdf-native.js')
    start = adapter.index(' function address(value,origin){') + len(' function address(value,origin){')
    end = adapter.index('\n function same(', start)
    body = adapter[start:end].strip().removesuffix('}').rstrip()
    marker = '/*__PADI_NATIVE_VIEWER_ADDRESS__*/'
    if runtime.count(marker) != 1:
        raise ValueError('Viewer address marker changed')
    runtime = runtime.replace(marker, body)
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    data = dict(versi=1, sumber=source, variants=variants, styles=styles, scripts=scripts, navigation=navigation)
    payload = ('/* Public native process PDF viewer layouts, no binary. */\nwindow.PadiKerangkaProsesPDFData='
               + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n' + runtime).encode()
    if len(payload) > 524288:
        raise ValueError('Process PDF viewer package exceeds bound')
    meta = dict(versi=1, sumber=source, variants=list(variants),
                aset_sha256=hashlib.sha256(payload).hexdigest(), inputs=hashes)
    return payload, (json.dumps(meta, ensure_ascii=False, indent=2) + '\n').encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, payload in zip(('kerangka-proses-pdf-ui.js', 'kerangka-proses-pdf-ui.meta.json'), build()):
        path = ROOT / 'app/web/static' / name
        if args.check:
            if path.read_bytes() != payload:
                raise AssertionError('Process PDF package stale: ' + name)
        else:
            path.write_bytes(payload)
        print(name, len(payload), 'bytes')


if __name__ == '__main__':
    main()
