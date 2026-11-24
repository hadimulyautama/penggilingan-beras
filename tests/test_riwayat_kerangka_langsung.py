"""Finite presentation descriptor tests; no actor/DB/permission claim."""
from pathlib import Path
import pytest
from app.web.riwayat_kerangka_langsung import valid, _style, inline_styles


def descriptor():
    return dict(versi=1,cap='fixture',konteks='fixture-context',sesi='fixture-session',
                penyandian='baris-1',potongan=['<section>native labels only</section>'],
                frames={'/riwayat-giling':[0]})


def test_finite_shape_accepts_native_list_but_not_arbitrary_detail_or_transfer():
    assert valid(descriptor())
    for path in ['/riwayat-giling/1','/riwayat-transfer','/riwayat-qc/beras-hasil-sosoh','/riwayat-giling?sebelum=1','/audit','https://foreign.invalid/riwayat-giling']:
        data=descriptor();data['frames']={path:[0]};assert not valid(data)


@pytest.mark.parametrize('patch',[
    {'versi':2},{'penyandian':'raw'},{'cap':''},{'sesi':''},
    {'konteks':None},{'frames':{}},{'frames':[]},{'potongan':[]},
    {'potongan':['']},{'potongan':[1]},{'frames':{'/riwayat-giling':[-1]}},
    {'frames':{'/riwayat-giling':[True]}},{'frames':{'/riwayat-giling':[1]}},
    {'frames':{'/riwayat-giling':[]}},{'potongan':['x'*524289]},
])
def test_invalid_or_oversize_descriptor_declines(patch):
    assert not valid({**descriptor(),**patch})


def test_extra_data_fields_cannot_enter_the_presentation_envelope():
    data=descriptor();data['rows']=[{'private':'not allowed'}]
    assert not valid(data)


def test_only_native_local_versioned_styles_are_inlined_without_editing_css():
    from bs4 import BeautifulSoup
    html='<html><body><main id="isi-halaman"><link rel="stylesheet" href="/static/riwayat.css?v=fixture"></main></body></html>'
    result=BeautifulSoup(inline_styles(html,'fixture'),'html.parser')
    assert result.select_one('[data-history-native-style]').string==_style('riwayat.css')
    assert not result.select('link')
    with pytest.raises(ValueError):inline_styles(html,'other-cap')


def test_authorization_and_original_native_readers_stay_in_the_call_path():
    source=(Path(__file__).parents[1]/'app/web/riwayat_kerangka_langsung.py').read_text()
    assert source.index('if not await _boleh(akun.user, path)')<source.index('response = await kerangka(')
    assert 'options = await pilihan(akun)' in source
    for forbidden in ['.commit(','.flush(','.add(','.delete(','create_all','SimpleNamespace','CustomerReader(']:
        assert forbidden not in source
