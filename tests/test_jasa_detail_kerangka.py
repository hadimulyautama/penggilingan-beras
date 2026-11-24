"""Pure customer-detail proposal tests: shape, descriptor and native source pins."""
import ast
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,DictLoader,Environment,FileSystemLoader,StrictUndefined
import pytest

from app.web.jasa_detail_kerangka import TABS,STATUS_PILIHAN,deskripsi,kunci_cetak

ROOT=Path(__file__).parents[1]


def rendered(tab='ringkasan',query='',many=False):
    model=deskripsi('/jasa/pelanggan/17','tab='+tab+('&'+query if query else ''))
    model.update(nama='Pelanggan sintetis terverifikasi',stamp='synthetic-context-stamp',filter_pesanan=many or bool(model['pesanan_cari'] or model['pesanan_status']))
    env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block isi %}{% endblock %}'}),
        FileSystemLoader([str(ROOT/'app/web/templates'),str(ROOT/'hmu_tampilan/templates')])]),
        undefined=StrictUndefined,autoescape=True)
    html=env.get_template('jasa_detail_kerangka.html').render(JASA_DETAIL_SHELL=model,VERSI='synthetic-release')
    return BeautifulSoup(kunci_cetak(html.encode()),'html.parser')


@pytest.mark.parametrize('tab,label',TABS)
def test_five_native_tabs_verified_identity_and_unknown_business_values_without_orm(tab,label):
    page=rendered(tab)
    links=page.select('.jasa-detail-tab>a')
    assert [x.get_text() for x in links]==[n for _,n in TABS]
    assert [x.get_text() for x in links if x.get('aria-current')=='page']==[label]
    assert page.h1.get_text()=='Pelanggan sintetis terverifikasi'
    assert not page.select('form[method=post],input[type=hidden],input[name=_csrf]')
    assert not page.select('[data-buka],[data-nilai],.jasa-catatan[id]')
    for print_ in page.select('[data-js-cetak]'):
        assert print_.has_attr('disabled') and print_['aria-describedby']=='jasa-detail-cetak-alasan'
    assert 'belum dibaca' in page.get_text().lower()
    assert not page.find(string=lambda x:x and ('0 kg' in x or '0 pesanan' in x or 'Tidak ada saldo tercatat saat ini' in x))
    for field in page.select('input,select'):
        assert field.has_attr('disabled')


def test_native_stock_columns_and_summary_balance_labels_preserved():
    assert [x.get_text() for x in rendered('stok').select('.jasa-stok__kepala>span')]==['Barang / sumber','Lokasi','Saldo']
    assert [x.get_text() for x in rendered().select('.jasa-detail-angka>div>span')]==['PK tersedia','Beras tersisa','Hasil samping']
    assert not rendered().select('.jasa-pesanan-filter')
    assert rendered(many=True).select('.jasa-pesanan-filter')
    assert rendered(query='pesanan_cari=ABC').select('.jasa-pesanan-filter')


@pytest.mark.parametrize('path,query',[
    ('/jasa/17',''),('/jasa/17/nota',''),('/jasa/pelanggan/0',''),('/jasa/pelanggan/017',''),
    ('/pelanggan/jasa/pelanggan/17',''),('/jasa/pelanggan/2147483648',''),
    ('/jasa/pelanggan/17','buka=tutup_jasa&nilai=1'),('/jasa/pelanggan/17','buka='),
    ('/jasa/pelanggan/17','pesanan_id=1'),('/jasa/pelanggan/17','tab=asing'),
    ('/jasa/pelanggan/17','tab=stok&tab=proses'),('/jasa/pelanggan/17','err=simpan'),
    ('/jasa/pelanggan/17','company_id=2'),('/jasa/pelanggan/17','pesanan_status=asing'),
    ('/jasa/pelanggan/17','rincian_halaman=-1'),('/jasa/pelanggan/17','pesanan_halaman=01'),
    ('/jasa/pelanggan/17','cari=%FF'),('/jasa/pelanggan/17','cari=%GG'),
])
def test_actions_feedback_focused_aliases_and_malformed_remain_native(path,query):
    assert deskripsi(path,query) is None


def test_known_native_filter_intent_and_carry_links_are_read_only():
    query='tab=proses&status=&cari=Batch&halaman=&pesanan_status=berjalan&rincian_halaman=2&rincian_cari=Lot'
    model=deskripsi('/jasa/pelanggan/17',query)
    assert model['alamat']=='/jasa/pelanggan/17?'+query
    assert model['rincian_cari']=='Lot' and model['pesanan_status']=='berjalan'
    assert all('/jasa/pelanggan/17?' in t['href'] and 'pesanan_status=berjalan' in t['href'] for t in model['tabs'])
    assert all('buka=' not in t['href'] and 'nilai=' not in t['href'] for t in model['tabs'])


def test_native_guard_and_local_namespace_are_reused_without_claiming_runtime_acl():
    tree=ast.parse((ROOT/'app/web/jasa_detail_kerangka.py').read_text())
    builder=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='kerangka')
    source=ast.unparse(builder)
    assert "getattr(request.state, 'portal_scope', None) is not None" in source
    assert 'can_see_financials(akun.user)' in source
    assert source.index('can_see_financials(akun.user)')<source.index('async with SessionLocal()')
    native=(ROOT/'app/services/jasa_pelanggan.py').read_text()
    metadata=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_metadata_pelanggan')
    text=ast.unparse(metadata)
    assert 'select(Pelanggan.id, Pelanggan.nama_pelanggan).where(Pelanggan.id == pid)' in text
    assert "person['nama_pelanggan']" in text
    assert "spec.update(nama=metadata['nama']" in source
    assert text.count('await db.execute(')==1 # reuses existence lookup, no extra customer-name query
    assert 'select(Jasa.id).where(Jasa.pelanggan_id == pid).limit(21)' in text
    sql="SELECT EXISTS(SELECT 1 FROM timbangan_transaksi WHERE arah='MASUK' AND jasa=TRUE AND pelanggan_id=:pid)"
    assert sql in native and sql in ast.get_source_segment((ROOT/'app/web/jasa_detail_kerangka.py').read_text(),metadata)
    assert "from app.database import SessionLocal" in source
    assert 'pasang_pagar(engine' in (ROOT/'app/database.py').read_text()
    assert not any(isinstance(n,ast.Attribute) and n.attr in {'commit','flush','add','delete'} for n in ast.walk(tree))


def test_filter_reference_choices_equal_native_static_status_catalog():
    native=ast.parse((ROOT/'app/services/jasa_pelanggan.py').read_text())
    status=next(n.value for n in native.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='STATUS' for t in n.targets))
    assert STATUS_PILIHAN==ast.literal_eval(status)
    assert [(x.get('value'),x.get_text()) for x in rendered(query='pesanan_status=berjalan').select('.jasa-pesanan-filter option')]==list(STATUS_PILIHAN)
