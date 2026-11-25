"""Source-only structure parity; no account, DB, browser, or fetch invocation."""
from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
import pytest

ROOT=Path(__file__).parents[1]


def env():
    return Environment(loader=ChoiceLoader([
        DictLoader({'base.html':'{% block isi %}{% endblock %}'}),
        FileSystemLoader([ROOT/'app/web/templates',ROOT/'hmu_tampilan/templates']),
    ]),autoescape=True,undefined=StrictUndefined)


def context(status='',search=''):
    return dict(VERSI='__PADI_CAP__',tapis=status,cari=search,
                STATUS_PILIHAN=[('','Semua status'),('berjalan','Berjalan')],
                JASA_SHELL=dict(stamp='__PADI_STAMP__',url='__PADI_DATA_URL__',filtered=bool(status or search)))


@pytest.mark.parametrize('status,search',[('',''),('berjalan',''),('','contoh <pelanggan>')])
def test_no_transitional_heading_and_native_controls_are_first(status,search):
    scope=context(status,search);engine=env()
    shell=BeautifulSoup(engine.get_template('jasa_bertahap.html').render(**scope),'html.parser')
    # Empty native list render does not fabricate customer rows.
    native=BeautifulSoup(engine.get_template('jasa.html').render(
        **scope,jumlah=0,kartu=[],akhir=1,halaman=1),'html.parser')
    root=shell.select_one('[data-jasa-bertahap]')
    assert root['aria-label']=='Pesanan Jasa' and not root.select('h1')
    assert not native.select('h1')
    assert str(root.select_one('[data-jasa-kontrol]'))==str(native.select_one('[data-jasa-kontrol]'))
    children=[c for c in root.children if getattr(c,'name',None)]
    first_visible=next(c for c in children if c.name not in ('link','script'))
    assert first_visible.has_attr('data-jasa-kontrol')
    panel=root.select_one('[data-jasa-baca-isi]')
    assert panel.select_one('[data-jasa-jumlah]').find_next_sibling()['class']==['jasa-daftar']
    assert root.select_one('#jasa-cetak-alasan').find_previous_sibling()==panel
    assert not root.select('form[method="post"],[data-post],[data-kirim],input[name="_csrf"]')


def test_placeholder_has_native_card_sections_without_customer_or_amounts():
    engine=env();shell=BeautifulSoup(engine.get_template('jasa_bertahap.html').render(**context()),'html.parser')
    card=shell.select_one('.jasa-pelanggan--memuat')
    assert card.select_one('.baris h2').get_text()=='Pelanggan'
    assert card.select_one('.baris .lencana').get_text()=='Jasa'
    assert card.select_one('.jasa-produk-ringkas .jasa-produk-label').get_text()=='PK dan hasil yang tersedia'
    assert [e.get_text() for e in card.select('.jasa-angka small')]==['PK tersedia','Beras tersisa','Hasil samping']
    assert [e.get_text() for e in card.select('.jasa-angka strong')]==['Memuat…']*3
    assert not card.select('a[href]')
    assert card.select_one('.jasa-buka button')['disabled']==''
    # Real native bahan macro's no-row branch contains this exact header only.
    expected=engine.from_string("{% from '_jasa_bahan.html' import bahan %}{{ bahan(d,none) }}").render(d={'bahan_titipan':[]})
    actual=card.select_one('.jasa-bahan');native=BeautifulSoup(expected,'html.parser').select_one('.jasa-bahan')
    assert actual.attrs==native.attrs
    assert [c.name for c in actual.children if c.name]==[c.name for c in native.children if c.name]
    assert list(actual.stripped_strings)==list(native.stripped_strings)


def test_read_controller_selectors_retained_without_modifying_controller():
    shell=BeautifulSoup(env().get_template('jasa_bertahap.html').render(**context()),'html.parser')
    for selector in ('[data-jasa-baca-isi]','[data-jasa-baca-status]','[data-jasa-baca-ulang]',
                     '[data-jasa-baca-pesan]','.jasa-pelanggan--memuat h2','.jasa-angka strong'):
        assert shell.select_one(selector),selector
    assert len(shell.select('[data-jasa-baca-status]'))==1
    assert len(shell.select('[data-jasa-baca-ulang]'))==1
