"""Public deep Stock structures from literal labels; no records/app/DB import."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, Environment, StrictUndefined, nodes
ROOT = Path(__file__).resolve().parents[1]


def native_shapes(env):
    """Native immutable SVG/CSS shape only, never a dummy dryer/stock object.

    The sole status-dependent extra class is deliberately omitted in pending
    state. No empty/filled status is asserted; visible labels say unread.
    """
    tree = env.parse(env.loader.get_source(env, '_beranda_alur.html')[0])
    result = {}
    for name, key in [('bentuk_silo', 'silo'), ('bentuk_dryer', 'dryer')]:
        macro = next(n for n in tree.find_all(nodes.Macro) if n.name == name)
        text = []
        for output in macro.body:
            if not isinstance(output, nodes.Output):
                raise ValueError('Native equipment shape requires review')
            for part in output.nodes:
                if isinstance(part, nodes.TemplateData):
                    text.append(part.data)
                elif (isinstance(part, nodes.CondExpr)
                      and isinstance(part.expr1, nodes.Const)
                      and part.expr1.value == ' alur-alat--terisi'
                      and part.expr2 is None):
                    # Structural shape retained without falsely claiming its
                    # state. Pin predicate as well, rather than blind minifying.
                    valid = isinstance(part.test, nodes.Name) and part.test.name == 'terisi' if key == 'silo' else isinstance(part.test, nodes.Getattr) and isinstance(part.test.node, nodes.Name) and part.test.node.name == 'd' and part.test.attr == 'terisi'
                    if not valid:
                        raise ValueError('Native equipment status condition changed')
                else:
                    raise ValueError('Native equipment shape became data-dependent')
        result[key] = ''.join(text)
    return result


def build():
    inputs = {Path(__file__).resolve(), ROOT/'app/web/static/kerangka-stock-detail-ui-runtime.js'}

    def module(name, path):
        inputs.add(path)
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
        return value

    helper = module('stock_detail_build_helpers', ROOT/'scripts/buat_kerangka_ui.py')
    # dataclass needs the pure module in sys.modules; it imports no app state.
    import sys
    path = ROOT/'app/web/stock_detail_native.py';inputs.add(path)
    spec = importlib.util.spec_from_file_location('stock_detail_public_metadata', path)
    native = importlib.util.module_from_spec(spec);sys.modules[spec.name] = native
    try:spec.loader.exec_module(native)
    finally:sys.modules.pop(spec.name, None)
    roots = [ROOT/'app/web', ROOT/'hmu_tampilan']
    env = Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates', inputs) for p in roots]), autoescape=True, undefined=StrictUndefined)
    native_chrome = module('stock_public_native_chrome', ROOT/'scripts/stock_sosoh_native_chrome.py').load(ROOT, env, inputs)
    for name in ['hmu_tampilan/templates/_stok_pk_detail.html', 'app/web/templates/stok_pk_karung.html',
                 'hmu_tampilan/templates/stok_produk_detail.html', 'hmu_tampilan/templates/_produk_kemasan.html',
                 'hmu_tampilan/templates/_stok_pk_qc.html', 'hmu_tampilan/templates/gudang.html',
                 'hmu_tampilan/templates/_beranda_alur.html', 'hmu_tampilan/templates/_stok.html',
                 'hmu_tampilan/templates/_benda.html']:
        inputs.add(ROOT/name)
    shapes = native_shapes(env)
    variants = {}
    for key in native.VARIANTS:
        # Blueprint uses metadata only, not a fake card or empty native data DTO.
        meta = native.metadata(key, mutu=key.startswith('pk-'))
        doc = BeautifulSoup(env.get_template('stock_detail_native.html').render(
            STOCK_DETAIL=meta, STOCK_STRUCTURE=native.structure(meta), STOCK_SHAPES=shapes, DETAIL_URL='__PADI_URL__',
            DETAIL_STAMP='__PADI_STAMP__', VERSI='__PADI_CAP__', ACTION_LABELS=[]), 'html.parser')
        if len(doc.select('[data-stock-detail-native]')) != 1 or doc.select('form,input,select,textarea,[data-post],[data-kirim],#lembar,script[type="application/json"]'):
            raise ValueError('Deep Stock blueprint must remain read-only, without DTO/editor')
        for link in doc.select('link[rel=stylesheet]'):
            name = link['href'].split('?')[0].removeprefix('/static/')
            if name != 'beranda-alur.css':
                raise ValueError('Unknown warehouse stylesheet')
            path = next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path)
            style = doc.new_tag('style');style['data-stock-detail-style'] = ''
            style.string = path.read_text();link.replace_with(style)
        for script in doc.select('script[src]'):
            name = script['src'].split('?')[0].removeprefix('/static/')
            if not name or '/' in name or '\\' in name:
                raise ValueError('Only local native program allowed')
            path = next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path)
            text = path.read_text()
            if 'document.currentScript' in text:
                raise ValueError('Native script requires context review')
            script.attrs.clear();script.string = text.replace('</script', '<\\/script')
        path = '/stok/pk/detail' if key.startswith('pk-') else '/stok-produk/detail' if key.startswith('product-') else '/gudang/'+key.rsplit('-', 1)[1]
        title = native.structure(meta)['title']
        variants[key] = dict(html=str(doc), title=title, **native_chrome(path,
            dict(breadcrumb_detail='PADI_LEAF_PLACEHOLDER', kembali='/' if key.startswith('warehouse-') else '/stok'), title))
    scripts, refs, styles, style_refs = {}, {}, {}, {}
    for v in variants.values():
        doc = BeautifulSoup(v['html'], 'html.parser')
        for node in doc.select('style[data-stock-detail-style]'):
            node['data-stock-detail-style-ref'] = helper.intern_text(styles, style_refs, node.string or '');node.clear()
        for node in doc.select('script:not([type])'):
            node['data-stock-detail-script'] = helper.intern_text(scripts, refs, node.string or '');node.clear()
        v['html'] = str(doc)
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    data = dict(versi=1, sumber=source, variants=variants, scripts=scripts, styles=styles)
    payload = ('/* Data-free native deep Stock structures. */\nwindow.PadiKerangkaStockDetailData='
               + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n'
               + (ROOT/'app/web/static/kerangka-stock-detail-ui-runtime.js').read_text()).encode()
    if len(payload) > 524288:
        raise ValueError('Deep Stock separate package limit exceeded')
    meta = dict(versi=1, sumber=source, variants=list(variants), aset_sha256=hashlib.sha256(payload).hexdigest(), inputs=hashes)
    return payload, (json.dumps(meta, ensure_ascii=False, indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check', action='store_true');args=parser.parse_args()
    for name, payload in zip(('kerangka-stock-detail-ui.js', 'kerangka-stock-detail-ui.meta.json'), build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=payload:raise AssertionError('Stock detail program stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')


if __name__=='__main__':main()
