"""Finite metadata only; no actor, DB, template or permission claim."""
from pathlib import Path
import pytest
from app.web.riwayat_kerangka_langsung import valid


def descriptor():
    return dict(versi=1,cap='fixture',konteks='fixture-context',sesi='fixture-session',sumber='a'*64,
                menu=dict(default='/riwayat-giling',tabs=dict(proses=dict(first='/riwayat-giling',allowed=['/riwayat-giling']))),
                targets=['/riwayat-giling'])


def test_finite_native_list_metadata_does_not_contain_cross_family_html():
    assert valid(descriptor())
    for path in ['/riwayat-giling/1','/riwayat-transfer','/riwayat-qc/beras-hasil-sosoh','/riwayat-giling?sebelum=1','/audit','https://foreign.invalid/riwayat-giling']:
        data=descriptor();data['targets']=[path];assert not valid(data)


@pytest.mark.parametrize('patch',[
    {'versi':2},{'cap':''},{'sesi':''},{'konteks':None},{'cap':'x'*513},
    {'sumber':'a'*63},{'sumber':'g'*64},{'targets':[]},{'targets':{}},
    {'targets':[1]},{'targets':['/riwayat-giling','/riwayat-giling']},
    {'menu':{}},{'menu':{'default':'/riwayat-giling','tabs':{}}},
    {'menu':{'default':'https://foreign.invalid','tabs':{}}},
    {'menu':{'default':'/riwayat-giling','tabs':{'proses':{'first':'/audit','allowed':['/riwayat-giling']}}}},
    {'menu':{'default':'/riwayat-giling','tabs':{'qc':{'first':'/riwayat-giling','allowed':['/riwayat-giling']}}}},
    {'menu':{'default':'/riwayat-sosoh','tabs':{'proses':{'first':'/riwayat-sosoh','allowed':['/riwayat-sosoh']}}}},
])
def test_invalid_metadata_declines(patch):
    assert not valid({**descriptor(),**patch})


@pytest.mark.parametrize('key', ['html','frames','potongan','rows','totals','data'])
def test_html_records_and_values_cannot_enter_the_envelope(key):
    data=descriptor();data[key]='not allowed';assert not valid(data)


def test_real_authority_decides_targets_without_rendering_or_transaction_reads():
    source=(Path(__file__).parents[1]/'app/web/riwayat_kerangka_langsung.py').read_text()
    assert source.index('not await _boleh(akun.user,path)')<source.index('targets.append(path)')
    assert 'options=await pilihan(akun)' in source
    for forbidden in ['.commit(','.flush(','.add(','.delete(','create_all','SimpleNamespace','BeautifulSoup','await kerangka(','render(']:
        assert forbidden not in source
