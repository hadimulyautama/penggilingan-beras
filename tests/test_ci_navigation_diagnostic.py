"""Manual diagnostics must not weaken the existing full CI or permit deployment."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
import yaml

BASE_JOBS = {'uji': '504b21e3407385caef6a850d2f1ce0b3e8ed3fc7992300ec967192f21939a309', 'dua-aplikasi': 'd873c1bf614e5740e1f06fba2408903801f68f80c1c40ccaeacfc50ebacfff2a', 'retur-dua-aplikasi': '5c8ca7ac89403cbdf13562911ac093fdc50116277bed553098840c3b4d3387d5', 'koreksi-bahan': '1425937efc50fa3f1cea059f8d7cbfe01ff7ccede7f460afedaa4f7db99320eb', 'safari': 'a895c8e6d8435b86fd37c3834092ec939ee8015a2bb94670ae5c1b810d251548'}
FIRST = ('uji', 'dua-aplikasi', 'retur-dua-aplikasi')
ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def check(workflow):
    assert set(workflow) == {'name', 'permissions', 'on', 'jobs'}
    assert workflow['permissions'] == {'contents': 'read'}
    assert set(workflow['on']) == {'workflow_dispatch'}
    choice = workflow['on']['workflow_dispatch']['inputs']['cakupan']
    assert choice['default'] == 'semua'
    assert choice['options'] == ['semua', 'koreksi-bahan', 'diagnostik-navigasi']
    assert set(workflow['jobs']) == set(BASE_JOBS)
    for name, original in workflow['jobs'].items():
        job = deepcopy(original)
        if name in FIRST:
            assert job.pop('if') == "${{ github.event.inputs.cakupan != 'koreksi-bahan' && github.event.inputs.cakupan != 'diagnostik-navigasi' }}"
        if name == 'safari':
            steps = job['steps']
            full = next(s for s in steps if s.get('name', '').startswith('Gudang kerja,'))
            assert full.pop('if') == "${{ github.event.inputs.cakupan != 'diagnostik-navigasi' }}"
            diag = next(s for s in steps if s.get('name', '').startswith('Diagnostik navigasi native'))
            upload = next(s for s in steps if s.get('name') == 'Simpan diagnostik native terisolasi')
            assert diag['if'] == "${{ github.event.inputs.cakupan == 'diagnostik-navigasi' }}"
            assert diag['env'] == {'DETAIL_OUT': '${{ runner.temp }}/padiflow-diagnostik-${{ matrix.browser }}'}
            assert 'continue-on-error' not in diag and '||' not in diag['run']
            assert 'python -m pytest -vv --tb=short tests/pg/test_stock_detail_owner_browser.py' in diag['run']
            assert "'not_full_ci': True" in diag['run']
            assert upload['if'] == "${{ always() && github.event.inputs.cakupan == 'diagnostik-navigasi' }}"
            assert upload['uses'] == 'actions/upload-artifact@v4'
            assert upload['with']['path'] == '${{ runner.temp }}/padiflow-diagnostik-${{ matrix.browser }}/'
            assert upload['with']['if-no-files-found'] == 'error'
            steps.remove(diag); steps.remove(upload)
        assert digest(job) == BASE_JOBS[name], name


def current():
    return yaml.load((ROOT / '.github/workflows/uji.yml').read_text(), Loader=yaml.BaseLoader)


def test_diagnostic_is_manual_only_and_all_thirteen_full_profiles_are_unchanged():
    check(current())


@pytest.mark.parametrize('bad', ['write', 'push', 'default', 'full', 'inside_source', 'mask_failure'])
def test_diagnostic_scope_guard_rejects_mutated_workflows(bad):
    value = current()
    if bad == 'write': value['permissions']['contents'] = 'write'
    elif bad == 'push': value['on']['push'] = {}
    elif bad == 'default': value['on']['workflow_dispatch']['inputs']['cakupan']['default'] = 'diagnostik-navigasi'
    elif bad == 'full': value['jobs']['uji']['strategy']['matrix']['profil'].pop()
    else:
        diag = next(s for s in value['jobs']['safari']['steps'] if s.get('name', '').startswith('Diagnostik navigasi native'))
        if bad == 'inside_source': diag['env']['DETAIL_OUT'] = '${{ github.workspace }}/bukti/diagnostik'
        else: diag['continue-on-error'] = 'true'
    with pytest.raises(AssertionError): check(value)
