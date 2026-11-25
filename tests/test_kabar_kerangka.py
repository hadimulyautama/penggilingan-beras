"""Kabar shell cannot mark read/open or invent a notification watermark."""
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment,FileSystemLoader,StrictUndefined
from app.web.kabar_kerangka import deskripsi
ROOT=Path(__file__).parents[1]

def test_shell_has_native_tabs_disabled_status_actions_and_no_personal_data():
    env=Environment(loader=FileSystemLoader([ROOT/'app/web/templates',ROOT/'hmu_tampilan/templates']),autoescape=True,undefined=StrictUndefined)
    t=env.get_template('kabar_kerangka.html')
    ctx={'VERSI':'code-fixture','KABAR_SHELL':{**deskripsi('/kabar'),'stamp':'fixture|/kabar'}}
    doc=BeautifulSoup(''.join(t.blocks['isi'](t.new_context(ctx))),'html.parser')
    assert len(doc.select('[data-kabar-native]'))==1
    assert len(doc.select('[data-kabar-native-tab]'))==2
    assert not doc.select('form,input,[name],[data-post],[data-kirim],h1')
    assert doc.select_one('#kb-jenis').has_attr('disabled')
    assert 'Jenis belum dibaca' in doc.get_text() and 'Tandai semua dibaca' in doc.get_text()
    assert not doc.select('.kb-item,time,[data-sampai]')
    assert all(b.has_attr('disabled') or b.has_attr('hidden') or b.has_attr('data-kb-panduan') or b.has_attr('data-kb-tutup') for b in doc.select('button'))

@pytest.mark.parametrize('query',['','tab=belum&batas=30','sampai=0','sebelum=1&batas=100','jenis=sumber_tak_dikenal'])
def test_native_read_choice_kept_without_claiming_kind_or_newest_watermark(query):
    d=deskripsi('/kabar',query);assert d and d['alamat']=='/kabar'+('?' +query if query else '')
    assert not {'rows','count','sampai','jenis_semua'}&set(d)

@pytest.mark.parametrize('query',['batas=0','batas=101','sampai=-1','sebelum=0','company_id=1','pesan=berhasil','tab=1&tab=2','batas=abc'])
def test_unsupported_query_is_native_not_new_filter_policy(query):
    assert deskripsi('/kabar',query) is None

def test_native_status_and_open_writers_untouched_and_not_used_by_shell():
    source=(ROOT/'app/web/layar_kabar.py').read_text()
    assert 'akun=Depends(butuh_akun)' in source
    assert source.index('shell=await dokumen(request,akun)')<source.index('jenis_semua = await svc.jenis_tersedia')
