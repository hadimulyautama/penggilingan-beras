"""Detail PK yang kehilangan saldo tetap HTML, aman, dan dapat dipulihkan."""
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select,text
from app.models import (User,MillingProcess,MillingProgressLog,PkGudang2Intake,
                        PkPurchaseBatch,PkTumpukanToSilo,InternalTransfer,ActivityLog)
from app.services import stok
from app.services.transfer import create_internal_transfer
from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
from tests.pg.test_stok_pk_qc import dunia,dunia_asal
from tests.pg.test_riwayat_giling import _klien
from hmu_identitas import peran as P

pytestmark=pytest.mark.asyncio


async def sidik(db):
    hasil={}
    for model in (MillingProcess,MillingProgressLog,PkGudang2Intake,PkPurchaseBatch,
                  PkTumpukanToSilo,InternalTransfer,ActivityLog):
        hasil[model.__tablename__]=await db.scalar(text(f'''SELECT md5(COALESCE(
            string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),''))
            FROM {model.__tablename__} t'''))
    return hasil


def pemulihan(response):
    assert response.status_code==404
    assert response.headers['content-type'].startswith('text/html')
    assert 'no-store' in response.headers['cache-control']
    assert response.headers['X-Pindah-Halaman']=='1'
    soup=BeautifulSoup(response.text,'html.parser')
    panel=soup.select_one('[data-stok-pk-tidak-tersedia]')
    assert panel and 'Stok PK tidak tersedia' in panel.get_text()
    assert soup.select_one('#kabar[role="status"]')
    assert not panel.select('form,button,[data-aksi]')
    link=panel.find('a',string='Lihat stok terbaru')
    assert link and link.has_attr('data-utuh')
    assert urlsplit(link['href']).path=='/stok'
    return link['href']


@pytest.mark.parametrize('gudang',['g1','g2'])
async def test_detail_lama_setelah_pindah_saldo_tidak_menampilkan_json_atau_aksi(pg,dunia,gudang):
    params={'gudang':gudang,'gudang_filter':gudang}
    if gudang=='g1':params['kode']='LOT-KODE-01'
    else:params['id']=str(dunia['beli_intake_id'])
    async with await _klien(pg,peran=P.OPERATOR,gudang='Gudang 2') as c:
        assert (await c.get('/stok/pk/detail',params=params)).status_code==200
        async with pg() as db:
            u=await db.get(User,dunia['user'].id)
            if gudang=='g1':
                await create_internal_transfer(db,user=u,kode_proses='LOT-KODE-01',lokasi_tujuan='ditumpuk',berat=2000)
                assert 'LOT-KODE-01' not in {r.kode for r in await stok.pk_gudang1(db)}
            else:
                await pindah_tumpukan_ke_silo(db,user=u,intake_id=dunia['beli_intake_id'],nama_silo='A',berat=9000)
                assert dunia['beli_intake_id'] not in {r.intake_id for r in await stok.pk_gudang2(db)}
            before=await sidik(db)
        for headers in ({},{'X-Pindah':'1'}):
            r=await c.get('/stok/pk/detail',params=params,headers=headers)
            balik=pemulihan(r)
            assert parse_qs(urlsplit(balik).query)['gudang']==[gudang]
            assert (await c.get(balik)).status_code==200
        # Penjaga saldo endpoint API tetap berfungsi, formatnya tetap JSON.
        if gudang=='g2':
            api=await c.get('/api/actions/rincian-masukkan-silo',params={'tumpukan':str(dunia['beli_intake_id'])})
            assert api.status_code==200 and api.json()['siap'] is False
            assert api.headers['content-type'].startswith('application/json')
            assert 'X-Pindah-Halaman' not in api.headers
            from tests.pg.formulir import cap_formulir
            tulis=await c.post('/api/actions/pindah-tumpukan-silo',
                json={'tumpukan':str(dunia['beli_intake_id']),'silo':'A','berat_kg':1},
                headers={'X-CSRF-Token':cap_formulir(c)})
            assert tulis.status_code==400 and 'detail' in tulis.json()
        async with pg() as db:assert await sidik(db)==before
        if gudang=='g2':Path('/private/tmp/padiflow-pk-pemulihan.html').write_text(r.text)


@pytest.mark.parametrize('params',[
    {'gudang':'g2','id':'999999'}, {'gudang':'g1','kode':'TIDAK-ADA'},
    {'gudang':'g2','id':'bukan-angka'}, {'gudang':'g3'}, {},
])
async def test_tautan_kedaluwarsa_dan_tidak_sah_tetap_punya_jalan_pulang(pg,dunia,params):
    async with await _klien(pg,peran=P.OPERATOR,gudang='Gudang 2') as c:
        pemulihan(await c.get('/stok/pk/detail',params=params))


@pytest.mark.parametrize('balik',[
    'https://contoh.invalid/stok','//contoh.invalid/stok','/api/actions/menu',
    '/stok?tab=bahan&pemilik=jasa&pelanggan_id=7&gudang=g2',
])
async def test_pemulihan_menjaga_pemilik_filter_dan_tujuan_internal(pg,dunia,balik):
    async with await _klien(pg,peran=P.OPERATOR,gudang='Gudang 2') as c:
        response=await c.get('/stok/pk/detail',params={
            'gudang':'g2','id':'999999','jasa':'1','gudang_filter':'g2',
            'kembali_stok':balik,'buka':'pindah_tumpukan_silo','nilai':'999999'})
        tujuan=pemulihan(response)
        assert not urlsplit(tujuan).netloc
        q=parse_qs(urlsplit(tujuan).query)
        assert q['pemilik']==['jasa'] and q['gudang']==['g2']
        assert 'buka' not in q and 'nilai' not in q
        assert 'LOT-KODE-01' not in response.text and 'PKB-KODE-01' not in response.text


async def test_operator_g1_tetap_tidak_melihat_detail_g2(pg,dunia):
    async with await _klien(pg,peran=P.OPERATOR,gudang='Gudang 1') as c:
        r=await c.get('/stok/pk/detail',params={'gudang':'g2','id':dunia['beli_intake_id']})
        pemulihan(r)
        assert 'PKB-KODE-01' not in r.text and 'UD Kode Bahan' not in r.text
