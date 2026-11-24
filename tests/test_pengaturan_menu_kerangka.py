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
       'blok_setelan','TAMPILAN_INDUK','tuan','blok_mode_uji','console_configured','kelola_darurat']


def page(path='/pengaturan',flags=None):
    env=Environment(loader=FileSystemLoader([str(ROOT/'app/web/templates'),str(ROOT/'hmu_tampilan/templates')]),undefined=StrictUndefined,autoescape=True)
    model={**spesifikasi(path,flags=flags),'stamp':'synthetic-stamp'}
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
    compiled=spesifikasi('/pengaturan',flags=dict.fromkeys(FLAGS,True))
    facilities=next(g for g in compiled['groups'] if g['id']=='fasilitas')['doors']
    assert [d['judul'] for d in facilities][:3]==['Perusahaan saya','Console Center','Identitas & logo perusahaan']
    assert facilities[1]['href'] is None
    recovery=page(flags=dict.fromkeys(FLAGS,True))
    assert recovery.select_one('.pg-darurat')
    assert not page(flags={'kelola_darurat':True}).select_one('.pg-darurat')
    assert not page(flags={'mode_uji_tersedia':True}).select('a[href="/pengaturan/mode-uji"]')


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
