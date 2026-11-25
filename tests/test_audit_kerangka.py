"""Data-free audit schema and finite read-only URL contract."""
from pathlib import Path
from bs4 import BeautifulSoup
import pytest
from app.web.audit_kerangka import alamat,metadata
ROOT=Path(__file__).parents[1]

def test_native_headers_and_filter_choices_are_source_derived():
    meta=metadata()
    assert meta['columns']==['Waktu / nomor','Aktivitas','Rincian','Pelaksana / status']
    assert [r[:2] for r in meta['RENTANG']]==[('48j','48 jam terakhir'),('24j','24 jam'),('semua','Semua')]
    assert [r[0] for r in meta['KELOMPOK']]==['semua','masuk','kering','giling','berhenti']
    assert len(BeautifulSoup(meta['header'],'html.parser').select('th'))==4

@pytest.mark.parametrize('query',['','rentang=24j','kelompok=masuk&cari=UJI%20%3Ckode%3E','rentang=semua&kelompok=giling&cari='])
def test_read_query_preserved_exact(query):
    assert alamat('/audit',query)=='/audit'+('?' +query if query else '')

@pytest.mark.parametrize('path,query',[
 ('/audit/batalkan',''),('/pelanggan/audit',''),('/audit','log_id=1'),('/audit','pesan=berhasil'),
 ('/audit','err=fixture'),('/audit','company_id=1'),('/audit','rentang=semua&rentang=24j'),
 ('/audit','rentang=unknown'),('/audit','kelompok=unknown'),('/audit','cari='+('a'*2049))])
def test_unadopted_feedback_mutation_or_scope_stays_native(path,query):
    assert alamat(path,query) is None

def test_native_caller_guard_still_precedes_presentation_and_undo_untouched():
    source=(ROOT/'app/web/layar_audit.py').read_text()
    assert 'akun=Depends(butuh_admin)' in source
    assert source.index('shell=await dokumen(request,akun)')<source.index('catatan, semua = await svc.daftar')
    undo=source[source.index('@router.post'):]
    assert 'log_id=log_id' in undo and 'actor=akun.user' in undo
    empty=(ROOT/'app/web/templates/audit_native.html').read_text()
    assert '{{ super() }}' in empty and '{% if LAPORAN_NAV and not catatan %}' in empty
