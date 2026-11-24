"""Pure structure proposal: no DB, account records, credentials or browser."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from starlette.requests import Request

from app.web.pengaturan_menu_kerangka import kerangka, spesifikasi

ROOT=Path(__file__).parents[1]
FLAGS=['blok_kerja_gudang','blok_lihat_sebagai','blok_perusahaan','blok_kelola',
       'blok_setelan','TAMPILAN_INDUK','tuan','blok_mode_uji','mode_uji_tersedia','kelola_darurat']


def page(path='/pengaturan',flags=None,console_url=''):
    env=Environment(loader=FileSystemLoader([str(ROOT/'app/web/templates'),str(ROOT/'hmu_tampilan/templates')]),undefined=StrictUndefined,autoescape=True)
    model={**spesifikasi(path,flags=flags,console_url=console_url),'stamp':'synthetic-stamp'}
    return BeautifulSoup(env.get_template('_pengaturan_menu_kerangka_isi.html').render(PG_MENU_SHELL=model),'html.parser')


def hrefs(flags):
    return {a['href'] for a in page(flags=flags).select('a[href]')}


def test_unknown_flags_preserve_only_native_unconditional_read_doors():
    assert hrefs({})=={'/pengaturan/akun','/pengaturan/sesi','/pengaturan/perusahaan-sendiri','/pengaturan/akses','/pengaturan/sistem'}
    unknown=page()
    assert not unknown.select('form,input[name],input[type=password],[aria-pressed]')
    assert 'Identitas akun belum dibaca' in unknown.get_text()
    assert not unknown.select('a[href^=http]')
    assert all(b.has_attr('disabled') or b.has_attr('hidden') for b in unknown.select('button'))


@pytest.mark.parametrize('value',['true','admin',1,object(),None])
def test_truthy_or_role_claims_cannot_unlock_conditional_doors(value):
    assert hrefs(dict.fromkeys(FLAGS,value))==hrefs({})
    assert hrefs({'role':'superadmin','is_super':True,'company_id':1})==hrefs({})


def test_actual_native_booleans_control_each_conditional_group_without_new_role_mapping():
    enabled=hrefs(dict.fromkeys(FLAGS,True))
    assert {'/pengaturan/peran','/pengaturan/perusahaan','/pengaturan/gudang',
        '/pengaturan/mesin','/pengaturan/silo','/pengaturan/jenis-proses','/pengguna',
        '/pengaturan/sebab-berhenti','/pengaturan/spesifikasi-beras','/pengaturan/hasil-samping',
        '/pengaturan/mutu','/pengaturan/kledo','/audit','/pengaturan/mode-uji'}<=enabled
    compiled=spesifikasi('/pengaturan',flags=dict.fromkeys(FLAGS,True),console_url='https://console-fixture.invalid/console')
    facilities=next(g for g in compiled['groups'] if g['id']=='fasilitas')['doors']
    assert [d['judul'] for d in facilities][:3]==['Perusahaan saya','Console Center','Identitas & logo perusahaan']
    assert facilities[1]['href']=='https://console-fixture.invalid/console'
    recovery=page(flags=dict.fromkeys(FLAGS,True))
    assert recovery.select_one('.pg-darurat')
    assert not page(flags={'kelola_darurat':True}).select_one('.pg-darurat')
    mode=page(flags={'mode_uji_tersedia':True}).find('strong',string='Mode uji').find_parent(class_='pg-pintu')
    assert mode.name=='span' and 'akses-terkunci' in mode['class']


@pytest.mark.parametrize('short,label',[(True,'Ganti pengguna'),(False,'Keluar'),(None,'Tindakan sesi belum dibaca')])
def test_session_controls_have_native_labels_only_when_variant_known_and_cannot_post(short,label):
    doc=page('/pengaturan/sesi',{'sesi_pendek':short})
    controls=doc.select('.setelan-sesi button')
    assert [b.get_text(strip=True) for b in controls]==[label,'Keluar dari semua perangkat']
    assert all(b.get('type')=='button' and b.has_attr('disabled') for b in controls)
    assert not doc.select('form,input,script')


@pytest.mark.parametrize('path,query',[
    ('/pengaturan/peran',''),('/pengaturan/akses',''),('/pengaturan/akun',''),
    ('/pengaturan','err=nama'),('/pengaturan/sesi','pesan=keluar'),('/pengaturan/sistem',''),
    ('/pengaturan','company_id=1'),('/pelanggan/pengaturan','')])
def test_other_settings_and_query_feedback_stay_native(path,query):
    assert spesifikasi(path,query) is None


@pytest.mark.asyncio
async def test_fresh_caller_required_no_read_before_decline_and_private_render(monkeypatch):
    from starlette.responses import HTMLResponse
    seen=[]
    def render(request,name,**context):
        seen.append((name,context));return HTMLResponse('pure structure render')
    monkeypatch.setitem(sys.modules,'app.web.tampilan',NS(render=render))
    account=NS(harus_ganti_sandi=False)
    request=Request(dict(type='http',method='GET',scheme='https',server=('uji',443),path='/pengaturan/sesi',query_string=b'',headers=[],state={}))
    context={'SHELL':{'data_url':'/pengaturan/sesi','stamp':'synthetic-stamp'},'PENGATURAN_NATIVE_FLAGS':{'sesi_pendek':False}}
    assert await kerangka(request,account,context) is None
    request.state.akun=account
    result=await kerangka(request,account,context)
    assert result.headers['cache-control']=='private, no-store'
    assert seen[0][1]['PG_MENU_SHELL']['session_label']=='Keluar'
    for key,value in [('portal_scope',object())]:
        setattr(request.state,key,value);assert await kerangka(request,account,context) is None
        setattr(request.state,key,None)
    account.harus_ganti_sandi=True
    assert await kerangka(request,account,context) is None
    account.harus_ganti_sandi=False;request.scope['method']='POST'
    assert await kerangka(request,account,context) is None
    assert len(seen)==1


def native_groups(flags,console_url=''):
    # Render the exact vendor group/macro source, without its account header,
    # record objects, base chrome or data forms. Only pure native UI flags.
    source=(ROOT/'hmu_tampilan/templates/pengaturan.html').read_text()
    macro=source[source.index('{% macro pintu('):source.index('{%- endmacro %}')+len('{%- endmacro %}')]
    begin=source.index('<div class="pg-kelompok">')
    fragment=source[begin:source.index('\n  </div>\n{% endif %}',begin)+len('\n  </div>')]
    app=(ROOT/'app/web/templates/pengaturan_fasilitas.html').read_text()
    own=app[app.index('{% block organisasi_pengaturan %}')+len('{% block organisasi_pengaturan %}'):app.index('{% endblock %}')]
    fragment=fragment.replace('{% block organisasi_pengaturan %}{% endblock %}',own)
    prefix="{% from '_pengaturan_ikon.html' import ikon %}{% import '_kata_pengaturan.html' as kata with context %}"
    env=Environment(loader=FileSystemLoader([str(ROOT/'app/web/templates'),str(ROOT/'hmu_tampilan/templates')]),undefined=StrictUndefined,autoescape=True)
    return BeautifulSoup(env.from_string(prefix+macro+fragment).render(**{**dict.fromkeys(FLAGS,False),**flags,'console_url':console_url}),'html.parser')


def menu_signature(doc):
    return [(node.name,node.select_one('strong').get_text(),node.get('href'),
             node.get('class'),node.get('aria-disabled'),node.get('title'))
            for node in doc.select('.pg-pintu')]


@pytest.mark.parametrize('flags',[
    dict.fromkeys(FLAGS,False),
    {**dict.fromkeys(FLAGS,False),'TAMPILAN_INDUK':True},
    dict.fromkeys(FLAGS,True),
    {**dict.fromkeys(FLAGS,True),'blok_mode_uji':False,'blok_kelola':False,'blok_perusahaan':False},
    {**dict.fromkeys(FLAGS,False),'blok_kerja_gudang':True,'mode_uji_tersedia':True},
])
@pytest.mark.parametrize('console_url',['','https://console-fixture.invalid/console'])
def test_native_enabled_hrefs_and_all_door_labels_order_classes_match(flags,console_url):
    expected=native_groups(flags,console_url)
    actual=page(flags=flags,console_url=console_url)
    assert menu_signature(actual)==menu_signature(expected)
    assert [x.get_text() for x in actual.select('details.pg-lanjutan>summary')]==[x.get_text() for x in expected.select('details.pg-lanjutan>summary')]
    assert actual.select_one('details.pg-lanjutan')


def test_unknown_conditional_slots_remain_locked_and_mode_note_is_outside_controls():
    doc=page()
    labels={node.select_one('strong').get_text():node for node in doc.select('.pg-pintu')}
    for name in ['Peran & gudang kerja','Identitas & logo perusahaan','Gudang','Mesin & line produksi',
                 'Silo','Jenis proses','Kelola pengguna','Kontak Kledo','Catatan audit']:
        assert labels[name].name=='span' and labels[name].get('aria-disabled')=='true'
    assert not doc.select('.pg-terik small')
    assert 'Keadaan Mode terik belum dibaca.' in doc.select_one('#pg-menu-pending').get_text()
