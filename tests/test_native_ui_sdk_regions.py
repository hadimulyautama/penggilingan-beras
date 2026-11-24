"""Generated staff layouts must be recognizable by the unchanged native SDK.

This is a structural contract, not a browser/permission/performance proof.
Portal uses its separate native router and has separate acceptance tests.
"""
import importlib.util
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('users_source_contract',ROOT/'scripts/buat_kerangka_pengguna.py')
contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)
PORTAL={'kerangka-portal-ui.meta.json','kerangka-portal-detail-ui.meta.json'}
PACKAGES=sorted(p for p in (ROOT/'app/web/static').glob('*kerangka*.meta.json') if p.name not in PORTAL)


@pytest.mark.parametrize('manifest',PACKAGES,ids=lambda p:p.name.removesuffix('.meta.json'))
def test_every_generated_staff_layout_meets_the_native_structural_gate(manifest):
    script=manifest.with_name(manifest.name.removesuffix('.meta.json')+'.js').read_text()
    prefix=re.search(r'window\.\w+Data\s*=',script)
    assert prefix,manifest.name
    data,_=json.JSONDecoder().raw_decode(script[prefix.end():])
    components=data.get('variants')
    if components is None:
        assert 'component' in data,manifest.name
        components={'component':data['component']}
    assert isinstance(components,dict) and components,manifest.name
    selector=contract.native_frame_selector()
    for variant,component in components.items():
        assert isinstance(component,dict),(manifest.name,variant)
        if manifest.name=='kerangka-muatan-ui.meta.json':
            # Its unchanged native permission chooses one of these two
            # layouts. Test BOTH, not a fabricated universal editable form.
            assert set(component)=={'title','brand','read','record','breadcrumbs'}
            fragments={key:component[key] for key in ('read','record')}
        else:
            fragments={'html':component.get('html')}
        for mode,html in fragments.items():
            assert isinstance(html,str),(manifest.name,variant,mode)
            assert BeautifulSoup(html,'html.parser').select_one(selector),(manifest.name,variant,mode)


def test_unnamed_content_does_not_satisfy_the_sdk_gate_but_a_named_region_does():
    selector=contract.native_frame_selector()
    old='<section data-pengguna-baca-native><h2>Daftarkan orang baru</h2></section>'
    assert not BeautifulSoup(old,'html.parser').select_one(selector)
    named=old.replace('<section ','<section aria-label="Kelola pengguna" ',1)
    assert BeautifulSoup(named,'html.parser').select_one(selector)
