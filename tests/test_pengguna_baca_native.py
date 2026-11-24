"""Pure user-layout contracts; not a proof of native auth or database scope."""
import ast
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from dataclasses import dataclass

import pytest
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,DictLoader,Environment,FileSystemLoader,select_autoescape
from starlette.requests import Request
from app.web.pengguna_baca_native import VARIANTS,spesifikasi,kerangka,catat_guard,akun_native,katalog,metadata
ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path,query,kind,search',[
    ('/pengguna','','staf',''),('/pengguna/12','','staf-detail',''),
    ('/pengguna/pelanggan','','pelanggan',''),('/pengguna/pelanggan/12','','pelanggan-detail',''),
    ('/pengguna/pelanggan','cari_akun=%20Budi%20&halaman_akun=2','pelanggan','Budi'),
    ('/pengguna/pelanggan','halaman_akun=0','pelanggan',''),
])
def test_actual_read_paths_only(path,query,kind,search):
    spec=spesifikasi(path,query);assert spec['kind']==kind and spec['search']==search
    assert spec['alamat']==path+('?' +query if query else '')


@pytest.mark.parametrize('path,query',[
    ('/pengguna/buat',''),('/pengguna/reset',''),('/pengguna/pelanggan/kontak',''),('/pengguna/pelanggan/buat',''),
    ('/pengguna/pelanggan/12/status',''),('/pengguna/0',''),('/pengguna/2147483648',''),
    ('/pengguna','ok=1'),('/pengguna/12','err=nama'),('/pengguna/pelanggan','ok=dibuat'),
    ('/pengguna/pelanggan','cari_akun=a&cari_akun=b'),('/pengguna/pelanggan','halaman_akun=xyz'),
    ('/pengguna/pelanggan','cari_akun=%FF'),('/pengguna/pelanggan','company_id=2'),
])
def test_actions_feedback_invalid_queries_remain_native(path,query):assert spesifikasi(path,query) is None


@pytest.mark.parametrize('variant',VARIANTS)
def test_native_fields_disabled_unknown_values_not_false_empty_or_one_time_credentials(variant):
    shape=metadata();kind='staf' if variant in {'staf','staf-super'} else variant
    path='/pengguna' if kind=='staf' else '/pengguna/12' if kind=='staf-detail' else '/pengguna/pelanggan' if kind=='pelanggan' else '/pengguna/pelanggan/12'
    value=spesifikasi(path);value.update(variant=variant,title='Nama fixture' if kind=='staf-detail' else shape['titles'][variant],nama='Nama fixture',customer=variant!='staf',roles=shape['roles'],columns=shape['columns'],stamp='fixture')
    env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block isi %}{% endblock %}'}),FileSystemLoader(str(ROOT/'app/web/templates')),FileSystemLoader(str(ROOT/'hmu_tampilan/templates'))]),autoescape=select_autoescape())
    html=env.get_template('pengguna_baca_native.html').render(PENGGUNA_BACA=value,VERSI='fixture-cap')
    doc=BeautifulSoup(html,'html.parser')
    assert len(doc.select('[data-pengguna-baca-native]'))==1
    assert not doc.select('form,[name],input[type=hidden],[data-post],[data-kirim]')
    assert all(n.has_attr('disabled') for n in doc.select('input,select,textarea'))
    assert all(n.has_attr('disabled') and n.get('type')=='button' for n in doc.select('button:not([data-pengguna-baca-retry])'))
    assert not any(n.has_attr('value') for n in doc.select('input:not([data-pengguna-cari])'))
    assert 'Semua orang yang aktif sudah punya akun' not in html
    assert 'Belum ada akun pelanggan' not in html
    assert not doc.select('.sandi-awal,[name=_csrf]')
    ids=[n['id'] for n in doc.select('[id]')]
    assert len(ids)==len(set(ids)), 'Pending structure may not duplicate native field IDs'
    for field in doc.select('input,select,textarea'):
        wraps=field.find_parent('label')
        explicit=doc.find_all('label',attrs={'for':field.get('id')}) if field.has_attr('id') else []
        assert (1 if wraps else 0)+len(explicit)==1, str(field)
        label=wraps or explicit[0]
        assert label.get_text(' ',strip=True), 'Every disabled field still needs an actual accessible label' 
    assert bool(doc.select('nav[aria-label="Jenis pengguna"] a[href="/pengguna/pelanggan"]'))==(variant!='staf' and variant!='staf-detail')
    if kind.startswith('pelanggan'):
        assert [n.get_text() for n in doc.select('thead th')]==shape['columns']
        assert doc.select_one('tbody td')['colspan']=='5'
    if kind=='staf':assert [n.get_text() for n in doc.select('h2')]==['Daftarkan orang baru','Buatkan akun','Akun yang ada']
    if kind=='staf-detail':
        assert doc.select_one('#peran option[selected]').get_text()=='Peran belum dibaca'
        assert doc.select_one('#mode option[selected]').get_text()=='Jenis perangkat belum dibaca'


def test_reference_roles_and_titles_are_pinned_native_source_not_actor_roles():
    from app.web.pengguna import PERAN
    shape=metadata();assert shape['roles']==[list(row) for row in PERAN]
    assert shape['titles']['staf-detail']=='__PADI_NAMA__'
    for p,digest in shape['inputs'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest


def test_caller_dependencies_guards_and_data_negotiation_do_not_enter_writers():
    targets={'app/web/pengguna.py':{'halaman_pengguna','halaman_ubah'},'app/web/portal/admin.py':{'index','detail'}}
    for path,names in targets.items():
        tree=ast.parse((ROOT/path).read_text());seen=set()
        for node in tree.body:
            if not isinstance(node,(ast.AsyncFunctionDef,ast.FunctionDef)):continue
            code=ast.unparse(node)
            if 'await kerangka(' not in code:continue
            assert node.name in names
            assert 'Depends(butuh_super)' in code or 'Depends(super_only)' in code
            assert code.index('catat_guard(')<code.index('await kerangka(')
            seen.add(node.name)
        assert seen==names
    code=(ROOT/'app/web/pengguna.py').read_text().split('async def halaman_ubah',1)[1].split('_ERR_UBAH =',1)[0]
    assert code.index('if a is None:')<code.index('await kerangka(')
    assert 'if not early:' in code and 'if early:' in code
    assert code.count('select(ProduksiAkun)')==1
    own=(ROOT/'app/web/pengguna_baca_native.py').read_text()
    assert not any(n in own for n in ('db.commit(', 'db.flush(', 'PortalAccount(', 'ProduksiAkun(', 'password_hash', 'create_all', 'APIRouter'))
    assert own.index('if not permintaan(request)')<own.index('from sqlalchemy import select')
    original=(ROOT/'app/web/templates/pengguna_pelanggan.html').read_text()
    assert '-kontak1' not in original and '/static/akun-pelanggan.js?v={{ VERSI }}' in original


@dataclass
class PrincipalMarker:
    harus_ganti_sandi:bool=False


def request(actor=None,path='/pengguna',headers=()):
    req=Request(dict(type='http',method='GET',path=path,query_string=b'',headers=list(headers)))
    req.state.akun=actor
    return req


def test_note_is_request_object_bound_not_an_id_or_role_inference():
    actor=PrincipalMarker();other=PrincipalMarker();req=request(actor)
    catat_guard(req,other,'staf');assert not hasattr(req.state,'pengguna_guard_staf')
    catat_guard(req,actor,'staf');assert req.state.pengguna_guard_staf is actor
    assert not akun_native(request(other),actor)
    req.state.portal_scope={};assert not akun_native(req,actor)
    actor.harus_ganti_sandi=True;assert not akun_native(request(actor),actor)


def test_data_get_declines_before_actor_queries_or_metadata():
    req=request(headers=[(b'x-pindah',b'1')])
    assert asyncio.run(kerangka(req,None,jenis='staf')) is None


def test_actual_guard_functions_are_reused_and_wrong_marker_not_accepted(monkeypatch):
    from app.web import security
    from app.web.portal import admin
    from app.web.pengguna_baca_native import pintu_native
    from fastapi import HTTPException
    actor=PrincipalMarker();req=request(actor);calls=[]
    async def staff(got):assert got is actor;calls.append('staff')
    async def customer(got):assert got is actor;calls.append('customer');raise HTTPException(403,'fixture native denial')
    monkeypatch.setattr(security,'butuh_super',staff);monkeypatch.setattr(admin,'super_only',customer)
    assert asyncio.run(pintu_native(req,actor))=={'staf':True,'pelanggan':False}
    assert asyncio.run(pintu_native(req,actor))=={'staf':True,'pelanggan':False}
    assert calls==['staff','customer','customer']


def permission():
    return dict(versi=1,cap='cap',konteks='context',sesi='session',sumber=__import__('app.web.pengguna_baca_native',fromlist=['aset']).aset()['sumber'],targets={'/pengguna':'staf-super','/pengguna/pelanggan':'pelanggan'})


def test_catalog_requires_actual_native_rows_not_route_shaped_ids_or_hidden_names():
    row='<div class="daftar-standar__baris baris"><div class="baris__isi"><div class="baris__nama">Nama asli fixture</div></div><a href="/pengguna/12">Ubah</a></div>'
    wrap=lambda body:'<div class="daftar-standar">'+body+'</div>'
    cat=lambda html:katalog(html,source_address='/pengguna',permission=permission())
    value=cat(wrap(row));assert value['entries']==[dict(alamat='/pengguna/12',variant='staf-detail',title='Nama asli fixture')]
    assert cat('<a href="/pengguna/12">Ubah</a>')['entries']==[]
    assert cat(wrap(row.replace('class="daftar-standar__baris baris"','class="daftar-standar__baris baris" hidden')))['entries']==[]
    assert cat(wrap(row.replace('/pengguna/12','/pengguna/reset')))['entries']==[]
    assert katalog(wrap(row),source_address='/pengguna',permission={**permission(),'targets':{}}) is None
    many=''.join(row.replace('/12','/'+str(i)) for i in range(1,202));assert cat(wrap(many)) is None


def test_customer_catalog_is_separate_and_keeps_native_page_limit():
    row='<tr><td>Nama pelanggan privat</td><td><a class="btn" href="/pengguna/pelanggan/12">Ubah akun / sandi</a></td></tr>'
    value=katalog('<section class="kelola-portal"><table><tbody>'+row+'</tbody></table></section>',source_address='/pengguna/pelanggan?cari_akun=Nama',permission=permission())
    assert len(value['entries'])==1 and value['entries'][0]['variant']=='pelanggan-detail'
    assert value['entries'][0]['title']==metadata()['titles']['pelanggan-detail']
    assert 'Nama pelanggan privat' not in json.dumps(value)


def test_generated_public_package_is_data_free_bounded_and_current():
    spec=importlib.util.spec_from_file_location('users_compiler',ROOT/'scripts/buat_kerangka_pengguna.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    payload,meta=module.build();assert payload==(ROOT/'app/web/static/kerangka-pengguna-ui.js').read_bytes();assert meta==(ROOT/'app/web/static/kerangka-pengguna-ui.meta.json').read_bytes()
    assert module.build()==(payload,meta) and len(payload)<=262144
    manifest=json.loads(meta)
    for path,digest in manifest['inputs'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    data=json.loads(payload.decode().split('window.PadiKerangkaPenggunaData=',1)[1].split(';\n',1)[0])
    assert set(data['variants'])==set(VARIANTS)
    for variant,entry in data['variants'].items():
        doc=BeautifulSoup(entry['html'],'html.parser');assert not doc.select('form,[name],input[type=hidden],[data-post],[data-kirim]')
        assert not any(s in entry['html'] for s in ('sandi_awal','password_hash','csrf','Nama asli fixture'))
        assert BeautifulSoup(entry['bar'],'html.parser').select_one('a.bar__balik')
        assert BeautifulSoup(entry['breadcrumb'],'html.parser').select_one('nav.desktop-breadcrumb')
    readonly=(ROOT/'app/web/static/pengguna-baca-native.js').read_text()
    assert not any(s in readonly for s in ('fetch(', 'sessionStorage', 'localStorage', 'history.pushState', 'submit('))


@pytest.mark.parametrize('path,allowed',[('/pengaturan',True),('/pengguna',True),('/pengguna/12',True),('/pengguna/pelanggan',True),('/pengguna/pelanggan/12',True),('/pengaturan/peran',False),('/barang-masuk',False),('/pengguna/pelanggan/kontak',False),('/pelanggan',False)])
def test_private_door_metadata_is_scoped_and_does_not_contain_accounts(path,allowed):
    from app.web.pengguna_baca_native import susun
    actor=PrincipalMarker();req=request(actor,path)
    catat_guard(req,actor,'staf');catat_guard(req,actor,'pelanggan')
    result=asyncio.run(susun(req,actor,registry=dict(cap='cap',konteks='context',sesi='session')))
    assert bool(result)==allowed
    if result:
        assert set(result)=={'versi','cap','konteks','sesi','sumber','targets'}
        assert result['targets']=={'/pengguna':'staf-super','/pengguna/pelanggan':'pelanggan'}
        assert not any(k in json.dumps(result) for k in ('nama','username','user_id','password'))


def test_catalog_overbudget_declines_without_truncating_or_guessing_rows():
    row=lambda i:'<div class="daftar-standar__baris"><div class="baris__nama">'+('&lt;'*200)+'</div><a href="/pengguna/'+str(i)+'">Ubah</a></div>'
    body='<div class="daftar-standar">'+''.join(row(i) for i in range(1,201))+'</div>'
    assert katalog(body,source_address='/pengguna',permission=permission()) is None


@pytest.mark.parametrize('html',[
    '<label>Username</label><input disabled>',
    '<label for="x">Nama</label><input id="x" disabled><input id="x" disabled>',
    '<label for="x">Nama</label><label for="x">Nama kedua</label><input id="x" disabled>',
    '<label><input disabled></label>',
])
def test_compiler_declines_missing_ambiguous_or_duplicate_field_labels(html):
    spec=importlib.util.spec_from_file_location('users_a11y_compiler',ROOT/'scripts/buat_kerangka_pengguna.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(ValueError):module.validate_fields(BeautifulSoup(html,'html.parser'))
