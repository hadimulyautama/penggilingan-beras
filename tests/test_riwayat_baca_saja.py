"""Klasifikasi marker pada History native; tanpa DB, browser atau hak baru."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape
import pytest
from starlette.requests import Request

from app.web.riwayat_baca_saja import riwayat_baca_saja

ROOT = Path(__file__).resolve().parents[1]
AUTO = object()


def akun(admin=False):
    return NS(user=NS(id=7), is_admin=admin, harus_ganti_sandi=False)


def request(actor, kind='giling', *, path=None, query=b'', method='GET', state=None):
    return Request(dict(type='http', method=method, scheme='https', server=('fixture.invalid',443),
        path=path or f'/riwayat-{kind}/12', query_string=query, headers=[], state={'akun':actor, **(state or {})}))


def decision(actor, req=None, *, kind='giling', ident=12, boleh=False):
    return riwayat_baca_saja(req or request(actor,kind),actor,jenis=kind,process_id=ident,boleh_koreksi=boleh)


@pytest.mark.parametrize('kind',['giling','sosoh'])
def test_only_same_authenticated_actor_native_empty_query_get_is_readonly(kind):
    actor=akun()
    assert decision(actor,kind=kind) is True


@pytest.mark.parametrize('value',[True,None,0,1,'','false',[],{}])
@pytest.mark.parametrize('field',['boleh','admin'])
def test_permissions_require_literal_false_not_falsy_or_missing(field,value):
    actor=akun(value if field=='admin' else False)
    assert decision(actor,boleh=value if field=='boleh' else False) is False


@pytest.mark.parametrize('query',[b'buka=',b'nilai=',b'buka=hasil_giling',b'koreksi=berhasil',b'koreksi_gagal=x',b'tab_detail=hasil',b'halaman_jeda=2',b'company_id=1',b'unknown='])
def test_action_feedback_filter_and_unknown_queries_keep_legacy_marker(query):
    actor=akun()
    assert decision(actor,request(actor,query=query)) is False


@pytest.mark.parametrize('method',['POST','PUT','PATCH','DELETE','HEAD'])
def test_non_get_cannot_be_classified_readonly(method):
    actor=akun()
    assert decision(actor,request(actor,method=method)) is False


@pytest.mark.parametrize('path',['/riwayat-giling/13','/riwayat-giling/012','/riwayat-giling/12/','/riwayat-giling/12/koreksi','/riwayat-giling/12/laporan','/proses-aktif/giling/12','/pelanggan/riwayat-giling/12','/riwayat-transfer/12'])
def test_only_exact_internal_resource_path_is_eligible(path):
    actor=akun()
    assert decision(actor,request(actor,path=path)) is False


@pytest.mark.parametrize('ident',[True,False,None,'12',0,-1,2147483648])
def test_unknown_or_invalid_resource_identity_keeps_marker(ident):
    assert decision(akun(),ident=ident) is False


def test_unknown_actor_or_portal_cannot_remove_marker():
    actor=akun()
    assert decision(actor,request(actor,state={'akun':akun()})) is False
    assert decision(actor,request(actor,state={'portal_scope':object()})) is False
    assert decision(None,request(None)) is False
    assert decision(actor,NS(method='GET')) is False
    assert decision(actor,request(actor),kind='pengeringan') is False
    del actor.is_admin
    assert decision(actor) is False
    actor=akun();actor.user=None
    assert decision(actor) is False
    for unknown in (None,True,0):
        actor=akun();actor.harus_ganti_sandi=unknown
        assert decision(actor) is False


def native_html(kind, *, admin=False, boleh=False, flag=AUTO, query=b'', portal=False, omit_flag=False):
    actor=akun(admin);req=request(actor,kind,query=query,state={'portal_scope':object()} if portal else None)
    if flag is AUTO:
        flag=decision(actor,req,kind=kind,boleh=boleh)
    k=NS(id=12,kode='KODE-SINTETIS',jasa=False,selesai=None,mulai=None,bahan_kg=10000,
        hasil_kg=6000,rendemen=60,belum_dicatat=False,pemakaian_silo=[],bahan=[],
        kelas='',mutu='',ditransfer_kg=0,tersedia_kg=6000,lama='',oleh='Pengguna sintetis',
        bahan_pasti=True,neraca_tercatat=None,silo=[],spek=[],
        beras=[NS(jenis='premium',nama='Premium',kg=6000,persen=75)],
        neraca=NS(bahan_kg=8000,keluar_kg=6000,timpang=False,bisa_dihitung=True,
            beras=NS(nama='Beras',kg=6000,persen=75),samping=[],susut=NS(nama='Susut',kg=2000,persen=25)))
    qc=NS(sampel=[],menunggu=0,sementara=True,jenis_label={'premium':'Premium'},
        komponen=[NS(nama='kadar_air',label='Kadar air')],sesi=[],catatan=[],hasil=[])
    env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block isi %}{% endblock %}{% block kaki %}{% endblock %}'}),FileSystemLoader(ROOT/'app/web/templates'),FileSystemLoader(ROOT/'hmu_tampilan/templates')]),autoescape=select_autoescape())
    env.filters['jam']=lambda value,*args:''
    context=dict(request=req,akun=actor,k=k,jenis=kind,VERSI='fixture-cap',VIEW='native-fixture',LIHAT_SEBAGAI=None,
        RIWAYAT_BACA_SAJA=flag,boleh_koreksi=boleh,PORTAL_READ_ONLY=portal,LAPORAN_NAV=False,
        kembali='/riwayat-'+kind,CSRF='fixture-csrf',hasil_koreksi=False,gagal_koreksi=None,
        penghalang_koreksi=None,catatan_penghalang=[],hasil_awal={'premium':6000,'broken':0} if kind=='sosoh' else 6000,
        isian_koreksi={},qc_gabah_asal=[],qc_sosoh=qc,qc_kode=k.kode,MUTU_AKTIF=True,
        jenis_hasil=['premium','broken'],nama_hasil=lambda name:name)
    if omit_flag:
        del context['RIWAYAT_BACA_SAJA']
    return BeautifulSoup(env.get_template('riwayat_'+kind+'_detail.html').render(**context),'html.parser')


@pytest.mark.parametrize('kind',['giling','sosoh'])
def test_actual_readonly_template_has_no_correction_qc_writer_or_post_controller(kind):
    doc=native_html(kind)
    main=doc.select_one('[data-riwayat-'+kind+']')
    assert main['data-history-readonly']=='1' and not main.has_attr('data-editor-perintah')
    assert not doc.select('form,input[name],textarea[name],[data-rhs-edit],[data-kirim],[data-aksi],[data-buka-aksi],[data-qc-editor],[data-qc-jenis],[data-qc-lengkapi],[data-qc-baru]')
    assert not doc.select('script[src*="qc-sosoh.js"],script[src*="koreksi-bahan"],script[src*="koreksi-di-detail"]')
    assert len(doc.select('.rhs-actions>a[href="/riwayat-'+kind+'/12/laporan"]'))==1
    # Shared aksi.js may be present, but has no automatic opening trigger.
    assert all(not node.get('data-buka') and not node.get('data-nilai') for node in doc.select('script[data-buka]'))


@pytest.mark.parametrize('kind',['giling','sosoh'])
@pytest.mark.parametrize('variant',['admin','inconsistent-actor','inconsistent-flag','action','portal','unknown-flag'])
def test_admin_action_unknown_and_inconsistent_metadata_keep_default_marker(kind,variant):
    options={'admin':False,'boleh':False}
    if variant=='admin':options.update(admin=True,boleh=True)
    elif variant=='inconsistent-actor':options.update(admin=True,flag=True)
    elif variant=='inconsistent-flag':options.update(boleh=True,flag=True)
    elif variant=='action':options.update(query=b'buka=')
    elif variant=='portal':options.update(portal=True)
    elif variant=='unknown-flag':options.update(flag='true')
    doc=native_html(kind,**options)
    main=doc.select_one('[data-riwayat-'+kind+']')
    assert main.has_attr('data-editor-perintah') and not main.has_attr('data-history-readonly')
    if variant=='admin':
        assert doc.select_one('.riwayat-koreksi__form')
        assert doc.select_one('[name="alasan"]')
        if kind=='sosoh':
            assert doc.select_one('[data-qc-editor]')
            assert doc.select_one('script[src*="qc-sosoh.js"]')


@pytest.mark.parametrize('name,kind',[('layar_riwayat','giling'),('layar_sosoh','sosoh')])
def test_only_native_get_render_wires_classification_after_existing_guards(name,kind):
    tree=ast.parse((ROOT/'app/web'/f'{name}.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='detail_riwayat_'+kind)
    calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='riwayat_baca_saja']
    assert len(calls)==1
    args={k.arg:ast.unparse(k.value) for k in calls[0].keywords}
    assert args=={'jenis':repr(kind),'process_id':'process_id','boleh_koreksi':'akun.is_admin'}
    assert [ast.unparse(n) for n in calls[0].args]==['request','akun']
    assert any(isinstance(n,ast.keyword) and n.arg=='RIWAYAT_BACA_SAJA' and n.value is calls[0] for n in ast.walk(fn))
    source=ast.unparse(fn)
    assert source.index('await _izin_lokasi')<source.index('riwayat_baca_saja(request')
    assert 'Depends(butuh_akun)' in source
    assert any(isinstance(n,ast.keyword) and n.arg=='boleh_koreksi' and ast.unparse(n.value)=='akun.is_admin' for n in ast.walk(fn))


@pytest.mark.parametrize('kind',['giling','sosoh'])
@pytest.mark.parametrize('flag',[None,False,0,1,'true'])
def test_template_never_treats_unknown_or_falsy_readonly_flag_as_literal_true(kind,flag):
    main=native_html(kind,flag=flag).select_one('[data-riwayat-'+kind+']')
    assert main.has_attr('data-editor-perintah') and not main.has_attr('data-history-readonly')


@pytest.mark.parametrize('kind',['giling','sosoh'])
def test_template_with_missing_classification_keeps_original_editor_marker(kind):
    main=native_html(kind,omit_flag=True).select_one('[data-riwayat-'+kind+']')
    assert main.has_attr('data-editor-perintah') and not main.has_attr('data-history-readonly')
