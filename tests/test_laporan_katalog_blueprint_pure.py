"""Pure catalog compiler proposal; no app imports, account, DB or browser."""
import ast
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
import pytest

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('catalog_proposal',ROOT/'scripts/kerangka_laporan_katalog.py')
catalog=importlib.util.module_from_spec(spec);spec.loader.exec_module(catalog)


def source():
    return (ROOT/'app/services/laporan_periode.py').read_text(),(ROOT/'app/web/laporan.py').read_text()


def navigation(allowed=True):
    # Public snapshot-shaped test metadata, not a synthetic role/account.
    return dict(aktif='laporan',judul='Laporan periode',jenis='laporan',detail=False,
        panduan='lk-panduan',pilihan=[],boleh_alamat=['/laporan'],tab=[
            dict(kunci='proses',nama='Riwayat proses',href='/riwayat-sosoh' if allowed else '',
                 boleh=allowed,alamat=['/riwayat-sosoh'] if allowed else []),
            dict(kunci='qc',nama='Riwayat QC',href='/riwayat-qc/pk-luar' if allowed else '',
                 boleh=allowed,alamat=['/riwayat-qc/pk-luar'] if allowed else []),
            dict(kunci='audit',nama='Audit',href='/audit' if allowed else '',
                 boleh=allowed,alamat=['/audit'] if allowed else [])])


def environment():
    return Environment(loader=ChoiceLoader([
        DictLoader({'base.html':'{% block isi %}{% endblock %}'}),
        FileSystemLoader([ROOT/'app/web/templates',ROOT/'hmu_tampilan/templates']),
    ]),autoescape=True,undefined=StrictUndefined)


def test_public_labels_and_periods_read_literal_without_evaluating_models():
    tahap,laporan=source();public=catalog.metadata_source(tahap,laporan)
    parsed=ast.parse(tahap);mapping=next(n.value for n in parsed.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='TAHAP' for t in n.targets))
    assert [(x['kode'],x['nama']) for x in public['daftar']]==[
        ('tahap_'+k.value,v.elts[0].value) for k,v in zip(mapping.keys,mapping.values)]
    assert len(public['daftar'])==13
    assert all(set(x)=={'kode','nama','arti','berperiode','boleh'} and x['boleh'] is True
               and x['berperiode'] is True for x in public['daftar'])
    assert public['periode'][0]==('hari_ini','Hari ini')
    # AST sees executable model expressions but never evaluates/imports them.
    rewritten=tahap.replace('m.PurchaseBatch','THIS_MUST_NEVER_EXECUTE()',1)
    assert catalog.metadata_source(rewritten,laporan)==public


@pytest.mark.parametrize('change',[
    lambda s:s.replace('False, None, berperiode=True','True, None, berperiode=True',1),
    lambda s:s.replace('(not lap.uang) or can_see_financials(user)','can_see_financials(user)',1),
    lambda s:s.replace('berperiode: bool = False','other_field: bool = False',1),
    lambda s:s.replace('from app.services.laporan_periode import TAHAP','from external import TAHAP',1),
])
def test_changed_public_or_permission_contract_requires_owner_review(change):
    tahap,laporan=source()
    with pytest.raises(ValueError):catalog.metadata_source(tahap,change(laporan))


@pytest.mark.parametrize('allowed',[True,False])
@pytest.mark.parametrize('induk',[True,False])
def test_actual_catalog_and_base_navigation_have_no_transitional_layout(allowed,induk):
    public=catalog.metadata(ROOT);nav=navigation(allowed);engine=environment()
    html=catalog.render_blueprint(engine,public=public,native_navigation=nav,
                                  cap='__PADI_CAP__',tampilan_induk=induk)
    doc=BeautifulSoup(html,'html.parser');wrapper=doc.select_one('.laporan-riwayat')
    assert wrapper.select_one('.laporan-nav').parent==wrapper
    assert wrapper.select_one('.laporan-isi').parent==wrapper
    assert wrapper.select_one('.laporan-nav').find_next_sibling(class_='laporan-isi')
    assert doc.select_one('[data-laporan-kontrol]')['data-aktif']=='laporan'
    assert json.loads(doc.select_one('[data-laporan-kontrol]')['data-tujuan-tab'])==nav['tab']
    assert not doc.select('h1,table,thead,form,input,[data-js-cetak],[data-lk-cetak],.kontrol-tab,.laporan-nav__pilihan')
    assert len(doc.select('[data-lk-buka="lk-panduan"]'))==1
    assert [x.get_text(strip=True) for x in doc.select('.lp-bagian-pilihan>h3')]==[
        'Penerimaan','Proses produksi','Perpindahan PK','Pengiriman dan retur']
    assert len(doc.select('.laporan-catalogue>a.lp-pintu'))==13
    assert set(a['href'] for a in doc.select('.lp-pintu'))=={
        '/laporan/'+x['kode'].removeprefix('tahap_') for x in public['daftar']}
    # Identical source template body, not a copy of catalogue labels/layout.
    native=BeautifulSoup(engine.get_template('laporan.html').render(**public,VERSI='__PADI_CAP__'),'html.parser')
    assert str(doc.select_one('.lp-pilihan'))==str(native.select_one('.lp-pilihan'))
    assert not doc.select('script:not([src]),[data-pindah-konteks],input[name="_csrf"]')


def test_navigation_is_exact_public_snapshot_copy_not_role_selection():
    nav=navigation(False);cloned=catalog.navigation_public(nav)
    assert cloned==nav and cloned is not nav
    nav['tab'][0]['alamat'].append('/changed')
    assert cloned['tab'][0]['alamat']==[]


@pytest.mark.parametrize('mutation',[
    lambda n:n.update(account_id='not-public'),
    lambda n:n.update(aktif='audit'),
    lambda n:n.update(detail=True),
    lambda n:n.update(pilihan=[('fake','Fake','/fake',None)]),
    lambda n:n['tab'][0].update(jumlah=0),
    lambda n:n['tab'][0].update(boleh='yes'),
])
def test_non_catalog_or_identity_or_count_metadata_is_not_compiled(mutation):
    nav=navigation();mutation(nav)
    with pytest.raises(ValueError):catalog.navigation_public(nav)


def test_input_pins_cover_authority_and_wrapper_sources():
    pins=catalog.source_pins(ROOT)
    assert 'app/web/laporan_navigasi.py' in pins
    assert 'hmu_tampilan/templates/base.html' in pins
    assert all(len(value)==64 for value in pins.values())
    source=(ROOT/'scripts/kerangka_laporan_katalog.py').read_text()
    tree=ast.parse(source)
    assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) and
        ('app.' in ast.unparse(n) or 'sqlalchemy' in ast.unparse(n)) for n in ast.walk(tree))
    base=(ROOT/'hmu_tampilan/templates/base.html').read_text()
    assert '<div class="laporan-riwayat"><link rel="stylesheet" href="/static/laporan-riwayat.css?v={{ VERSI }}">{% include "_laporan_navigasi.html" %}<div class="laporan-isi">' in base
