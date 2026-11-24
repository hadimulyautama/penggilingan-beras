"""Compile real native hierarchy/Back markup without app/model/DB import."""
import importlib.util
from pathlib import Path
import re


def load(root, env, inputs):
    path = Path(root)/'app/web/breadcrumb.py';inputs.add(path)
    spec = importlib.util.spec_from_file_location('stock_sosoh_build_breadcrumb', path)
    native = importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
    base = Path(root)/'hmu_tampilan/templates/base.html';inputs.add(base)
    match = re.search(r'<a class="bar__balik"[\s\S]*?</a>', base.read_text())
    if match is None or 'href="{{ kembali }}"' not in match[0]:
        raise ValueError('Native mobile Back requires review')
    mobile = env.from_string(match[0]).render(kembali='PADI_BACK_PLACEHOLDER')

    def compile(path, context, title):
        return dict(breadcrumb=env.get_template('_breadcrumb.html').render(
                        rantai=native.susun(path, context, title)), back_markup=mobile)

    return compile
