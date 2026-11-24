"""Compile two native Sosoh structures: labels are private, no app/DB import."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


def build():
    inputs = {Path(__file__).resolve(), ROOT/'app/web/static/kerangka-sosoh-ui-runtime.js'}

    def module(name, path):
        inputs.add(path)
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value

    helper = module('sosoh_public_build_helpers', ROOT/'scripts/buat_kerangka_ui.py')
    native = module('sosoh_public_metadata', ROOT/'app/web/sosoh_native_html.py')
    roots = [ROOT/'app/web', ROOT/'hmu_tampilan']
    env = Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates', inputs) for p in roots]),
                      autoescape=True, undefined=StrictUndefined)
    chrome = module('sosoh_public_native_chrome', ROOT/'scripts/stock_sosoh_native_chrome.py').load(ROOT, env, inputs)

    def asset(address):
        u = urlsplit(address)
        name = u.path.removeprefix('/static/')
        if u.scheme or u.netloc or not u.path.startswith('/static/') or not name or '/' in name or '\\' in name:
            raise ValueError('Only native local program assets allowed')
        path = next(p/'static'/name for p in roots if (p/'static'/name).is_file())
        inputs.add(path)
        return path.read_text()

    def css(address, seen=()):
        path = urlsplit(address).path
        if path in seen or len(seen) >= 8:
            raise ValueError('Recursive native stylesheet')
        text = re.sub(r"@import\s+url\(['\"](/static/[^'\"]+)['\"]\);",
                      lambda match: css(match[1], (*seen, path)), asset(address))
        if '@import' in text or '</style' in text.lower():
            raise ValueError('Unreviewed native stylesheet import')
        return helper.compact_css_comments(text)

    inputs.add(ROOT/'app/web/templates/_qc_sosoh.html')
    variants = {}
    for layout in ('admin', 'operator'):
        spec = native.deskripsi('/proses-aktif/sosoh/PADI_CODE_PLACEHOLDER')
        spec.update(layout=layout, hasil_utama=(), hasil_lain=(), qc=native.qc_headers(),
                    stamp='__PADI_STAMP__', blueprint=True)
        context = dict(SOSOH_KERANGKA=spec, VERSI='__PADI_CAP__', kembali='/pekerjaan?tab=berjalan')
        template = env.get_template('sosoh_native_html.html')
        doc = BeautifulSoup(''.join(template.blocks['isi'](template.new_context(context))), 'html.parser')
        root = doc.select_one('[data-sosoh-native-html]')
        if (not root or root.get('data-layout') != layout
                or doc.select('form,input:not([disabled]),#sosoh-awal,[data-sosoh-ringkas],[data-post],[data-kirim]')
                or root.select('[data-sn-output-kind]') or len(doc.select('template[data-sn-output-template]')) != 1):
            raise ValueError('Public Sosoh must remain data-free/disabled, without active core')
        styles = []
        for link in doc.select('link[rel=stylesheet]'):
            styles.append(css(link['href']))
            link.decompose()
        style = doc.new_tag('style', attrs={'data-sosoh-ui-style': ''})
        style.string = '\n'.join(styles)
        root.insert(0, style)
        for script in doc.select('script[src]'):
            text = asset(script['src'])
            if 'document.currentScript' in text:
                raise ValueError('Native script context requires review')
            script.attrs.clear()
            script.string = text.replace('</script', '<\\/script')
        variants[layout] = dict(html=str(doc), **chrome('/proses-aktif/sosoh/PADI_CODE_PLACEHOLDER',
            dict(kembali='/pekerjaan?tab=berjalan', breadcrumb_detail='PADI_CODE_PLACEHOLDER'),
            'Penyosohan PADI_CODE_PLACEHOLDER'))
    styles, scripts, style_refs, script_refs = {}, {}, {}, {}
    for variant in variants.values():
        doc = BeautifulSoup(variant['html'], 'html.parser')
        for selector, pool, refs, attr in [('style', styles, style_refs, 'data-sosoh-style'),
                                          ('script:not([type])', scripts, script_refs, 'data-sosoh-script')]:
            for node in doc.select(selector):
                node[attr] = helper.intern_text(pool, refs, node.string or '')
                node.clear()
        variant['html'] = str(doc)
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    data = dict(versi=1, sumber=source, variants=variants, styles=styles, scripts=scripts)
    payload = ('/* Public native Sosoh structure, no grade or process data. */\nwindow.PadiKerangkaSosohData='
               + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n'
               + (ROOT/'app/web/static/kerangka-sosoh-ui-runtime.js').read_text()).encode()
    if len(payload) > 524288:
        raise ValueError('Public Sosoh package exceeds separate bound')
    meta = dict(versi=1, sumber=source, variants=list(variants),
                aset_sha256=hashlib.sha256(payload).hexdigest(), inputs=hashes)
    return payload, (json.dumps(meta, ensure_ascii=False, indent=2)+'\n').encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, payload in zip(('kerangka-sosoh-ui.js', 'kerangka-sosoh-ui.meta.json'), build()):
        path = ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes() != payload:
                raise AssertionError('Generated Sosoh package stale: '+name)
        else:
            path.write_bytes(payload)
        print(name, len(payload), 'bytes')


if __name__ == '__main__':
    main()
