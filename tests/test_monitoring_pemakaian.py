"""Monitoring tidak mengubah respons, formulir, atau keberhasilan pekerjaan."""
import asyncio,uuid
import pytest
from hmu_identitas.monitoring import MonitoringHTTP,PengumpulPemakaian,PelakuPemakaian,perangkat_dari

@pytest.fixture
def ruang(monkeypatch):
    monkeypatch.setenv('HMU_COMPANY_ID','1');monkeypatch.setenv('HMU_RUANG_DATA',str(uuid.uuid4()));monkeypatch.setenv('HMU_SESI_LAMA_SAMPAI','0')

@pytest.mark.asyncio
@pytest.mark.parametrize('content,method,path,inject',[(b'text/html','GET','/stok',True),(b'text/event-stream','GET','/api/aliran',False),(b'application/json','POST','/pekerjaan',False)])
async def test_aliran_dan_formulir_tetap_utuh(ruang,content,method,path,inject):
    chunks=[b'<html><body><form><input value="belum disimpan">',b'</form></bo',b'dy></html>'];sent=[]
    async def app(scope,receive,send):
        await send(dict(type='http.response.start',status=200,headers=[(b'content-type',content),(b'content-length',str(sum(map(len,chunks))).encode())]))
        for i,chunk in enumerate(chunks):await send(dict(type='http.response.body',body=chunk,more_body=i<len(chunks)-1))
    collect=PengumpulPemakaian(None,'padiflow')
    middleware=MonitoringHTTP(app,pengumpul=collect,pelaku=lambda _:PelakuPemakaian('staf',2),skrip='/monitor.js')
    await middleware(dict(type='http',method=method,path=path,state={'akun':True},headers=[]),None,sent.append_async if hasattr(sent,'append_async') else _send(sent))
    body=b''.join(x.get('body',b'') for x in sent)
    assert body.replace(b'<script src="/monitor.js" defer></script>',b'')==b''.join(chunks)
    assert (b'/monitor.js' in body)==inject
    assert (b'content-length' in dict(sent[0]['headers']))!=inject

def _send(sent):
    async def send(msg):sent.append(msg)
    return send

@pytest.mark.asyncio
async def test_gangguan_statistik_tidak_mengubah_respons_dan_exception(ruang):
    class Rusak:
        def catat(self,*a,**kw):raise RuntimeError('database monitoring offline')
    async def app(scope,receive,send):
        await send(dict(type='http.response.start',status=201,headers=[]))
        await send(dict(type='http.response.body',body=b'tersimpan'))
    scope=dict(type='http',method='POST',path='/pekerjaan',state={},headers=[]);sent=[]
    await MonitoringHTTP(app,pengumpul=Rusak(),pelaku=lambda _:None)(scope,None,_send(sent))
    assert sent[0]['status']==201 and sent[-1]['body']==b'tersimpan'
    async def broken(*args):raise ValueError('galat aplikasi')
    collect=PengumpulPemakaian(None,'padiflow')
    with pytest.raises(ValueError):await MonitoringHTTP(broken,pengumpul=collect,pelaku=lambda _:None)(scope,None,_send([]))
    assert collect.antrean.get_nowait()['kode']=='500'

def test_antrean_terbatas_dan_tidak_merekam_ua_atau_payload(ruang):
    c=PengumpulPemakaian(None,'padiflow');actor=PelakuPemakaian('staf',1)
    for _ in range(100):c.catat(actor,jenis='interaksi',ua='Mozilla iPhone Safari/1 nilai-rahasia')
    assert c.antrean.qsize()==16
    row=c.antrean.get_nowait();assert row['browser']=='safari' and row['perangkat']=='iphone'
    assert 'nilai-rahasia' not in str(row)
    for _ in range(5000):c.catat(actor,jenis='respons_web',kode='200')
    assert c.antrean.qsize()==4096 and c.dibuang>0
