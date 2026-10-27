"""Detail baru memakai endpoint lama; bobot historis dan saldo tidak bercampur."""
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select, func
from app.models import InternalTransfer, PermintaanPk, User, Warehouse
from app.services import transfer, permintaan_pk
from tests.pg.test_permintaan_empat_langkah import pabrik, _minta, _acc, _kirim
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio
TABS=['ringkasan','bahan','permintaan','riwayat']


async def _status(pg, pid):
    async with pg() as db:
        p=await db.get(PermintaanPk,pid)
        return p.status,p.internal_transfer_id


async def _saldo(pg, lot):
    from app.penggilingan.gudang2.service import hitung_stok_silo
    from app.models import Silo
    async with pg() as db:
        stok=[]
        for s in (await db.scalars(select(Silo).join(Warehouse).where(Warehouse.kode_fungsi=='g2').order_by(Silo.id))).all():
            stok.append(await hitung_stok_silo(db,s.id))
        return await transfer.pending_transfer_kg(db,lot),stok,await db.scalar(select(func.count()).select_from(InternalTransfer))


async def _potret(c,url,tahap):
    for tab in TABS:
        r=await c.get(url+('&' if '?' in url else '?')+'tab_detail='+tab)
        assert r.status_code==200,(url,r.text[:200])
        assert r.text.count('role="tab"')==4
        assert f'aria-labelledby="tab-{tab}" >' in r.text
        assert 'Rp ' not in r.text and 'HPP' not in r.text and 'kg kg' not in r.text
        if os.environ.get('UJI_POTRET_TRANSFER'):
            Path('/tmp/transfer-pk-'+tahap+'-'+tab+'.html').write_text(r.text)
    return r


@pytest.mark.parametrize('peran',['admin','superadmin'])
async def test_empat_bobot_koreksi_tutup_dan_akses(pg,pabrik,peran):
    from app.web import csrf
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as g2, await _klien(pg,peran='operator',gudang='Gudang 1') as g1, await _klien(pg,peran=peran) as c:
        for x in (g1,g2,c):x.headers[csrf.NAMA_HEADER]=cap_formulir(x)
        if os.environ.get('UJI_TRANSFER_HIDUP') and peran=='admin':
            Path('/tmp/transfer-hidup-session.json').write_text(json.dumps({
                'cookies':{'admin':{cookie.name:cookie.value for cookie in c.cookies.jar},'g1':{cookie.name:cookie.value for cookie in g1.cookies.jar},'g2':{cookie.name:cookie.value for cookie in g2.cookies.jar}},
                'lot':pabrik['lot'],'process':pabrik['proses_id']}))
            return
        # Kewenangan meminta tetap milik operator G2.
        assert (await g2.post('/api/actions/minta-pk-g1',json={'kode_proses':pabrik['lot'],'berat':4400})).status_code==200
        async with pg() as db:pid=await db.scalar(select(PermintaanPk.id))
        url=f'/permintaan-pk/{pid}?kembali_kerja=%2Fpekerjaan%3Ftab%3Dtindakan%26jenis%3Dtransfer'
        await _potret(c,url,'diminta')
        assert (await g2.get(url)).status_code==403
        assert (await g1.get(url)).status_code==403
        assert '/permintaan-pk/'+str(pid) in (await c.get('/pekerjaan')).text
        asal=await _saldo(pg,pabrik['proses_id'])
        assert asal[0]==6000 and asal[2]==0
        # Persetujuan dapat melebihi permintaan; sumber stok tetap batas lama.
        assert (await c.post('/api/actions/acc-permintaan-pk',json={'permintaan':str(pid),'tujuan':'A','berat':5000})).status_code==200
        assert await _saldo(pg,pabrik['proses_id'])==asal
        await _potret(c,url,'disetujui')
        assert (await g1.get(url)).status_code==200
        assert 'buka=kirim_permintaan_pk' in (await g1.get(url)).text
        assert '/permintaan-pk/'+str(pid) in (await g1.get('/pekerjaan')).text
        assert (await g1.post('/api/actions/kirim-permintaan-pk',json={'permintaan':str(pid),'berat':5001})).status_code==400
        assert (await g1.post('/api/actions/kirim-permintaan-pk',json={'permintaan':str(pid),'berat':4600})).status_code==200
        _,tid=await _status(pg,pid)
        assert await _saldo(pg,pabrik['proses_id'])==(1400,[4600,0],1)
        r=await _potret(c,url,'dikirim')
        for teks in ['4.400 kg','5.000 kg','4.600 kg','Belum tercatat','buka=tutup_permintaan_pk']:
            assert teks in r.text,teks
        before=await _saldo(pg,pabrik['proses_id'])
        await _potret(c,f'/riwayat-transfer/{tid}','transfer-dikirim')
        assert await _saldo(pg,pabrik['proses_id'])==before
        assert (await g1.post('/api/actions/kirim-permintaan-pk',json={'permintaan':str(pid),'berat':4600})).status_code==400
        assert (await c.post('/api/actions/tutup-permintaan-pk',json={'permintaan':str(pid),'berat':4400})).status_code==200
        _,baru=await _status(pg,pid)
        assert baru!=tid
        assert await _saldo(pg,pabrik['proses_id'])==(1600,[4400,0],2)
        r=await _potret(c,url,'selesai')
        assert '−200 kg' in r.text
        async with pg() as db:
            p=await db.get(PermintaanPk,pid)
            assert p.berat_kirim_kg==4600 and p.berat_final_kg==4400
            assert (await db.get(InternalTransfer,tid)).status=='dibatalkan'
        old=await _potret(c,f'/riwayat-transfer/{tid}','asal-dibatalkan')
        assert '4.600 kg' in old.text and 'Dibatalkan' in old.text
        assert '1.600 kg' in old.text
        await _potret(c,f'/riwayat-transfer/{baru}','pengganti')
        assert (await g2.get(f'/riwayat-transfer/{baru}')).status_code==403
        assert (await g2.post('/api/actions/transfer-pk',json={'kode_proses':pabrik['lot'],'tujuan':'B','berat':100})).status_code==403
        if os.environ.get('UJI_POTRET_TRANSFER'):
            Path('/tmp/transfer-pk-session.json').write_text(json.dumps({'cookies':{cookie.name:cookie.value for cookie in c.cookies.jar},'allCookies':{'admin':{cookie.name:cookie.value for cookie in c.cookies.jar},'g1':{cookie.name:cookie.value for cookie in g1.cookies.jar},'g2':{cookie.name:cookie.value for cookie in g2.cookies.jar}},'url':url,'transfer':baru,'old':tid,'request':pid}))


async def test_koreksi_gagal_isian_tetap_dan_nol(pg,pabrik):
    async with pg() as db:
        r=await transfer.create_internal_transfer(db,user=await db.get(User,pabrik['admin']),kode_proses=pabrik['lot'],lokasi_tujuan='ditumpuk',berat=1000)
        tid=r.transfer.id
    async with await _klien(pg,peran='admin') as c:
        url=f'/riwayat-transfer/{tid}'
        await _potret(c,url,'langsung')
        before=await _saldo(pg,pabrik['proses_id'])
        form={'_csrf':cap_formulir(c),'hasil_transfer':'900','dasar_transfer':'999','alasan':'Koreksi nyata <uji>','kembali_kerja':'/pekerjaan?tab=berjalan'}
        r=await c.post(url+'/koreksi',data=form)
        assert r.status_code==422 and 'Koreksi nyata &lt;uji&gt;' in r.text
        assert 'value="900"' in r.text and 'periksa_ulang' in r.text
        assert f'/riwayat-transfer/{tid}/koreksi?tab_detail' not in r.text
        assert 'href="/pekerjaan?tab=berjalan"' in r.text
        assert 'aria-labelledby="tab-riwayat" >' in r.text
        assert await _saldo(pg,pabrik['proses_id'])==before
        if os.environ.get('UJI_POTRET_TRANSFER'):
            Path('/tmp/transfer-pk-gagal-riwayat.html').write_text(r.text)
        form.update(hasil_transfer='0',dasar_transfer='1000',periksa_ulang='ya',wajib_periksa='1')
        r=await c.post(url+'/koreksi',data=form)
        assert r.status_code==200 and 'berat akhir transfer 0 kg' in r.text
        assert 'kembali_kerja=' in str(r.url)
        async with pg() as db:
            assert (await db.get(InternalTransfer,tid)).status=='dibatalkan'
            assert await db.scalar(select(func.count()).select_from(InternalTransfer))==1
        await _potret(c,url,'koreksi-nol')


async def test_riwayat_paginasi_tidak_mengubah_saldo_dan_tab(pg,pabrik):
    async with pg() as db:
        u=await db.get(User,pabrik['admin'])
        for _ in range(21):
            r=await transfer.create_internal_transfer(db,user=u,kode_proses=pabrik['lot'],lokasi_tujuan='ditumpuk',berat=10)
        tid=r.transfer.id
    async with await _klien(pg,peran='admin') as c:
        url=f'/riwayat-transfer/{tid}'
        a=await c.get(url+'?halaman_transfer=2')
        assert 'Halaman 2 / 2' in a.text and '5.790 kg' in a.text
        if os.environ.get('UJI_POTRET_TRANSFER'):
            Path('/tmp/transfer-pk-paginasi-2-riwayat.html').write_text(a.text)
            Path('/tmp/transfer-pk-paginasi-1-riwayat.html').write_text((await c.get(url+'?tab_detail=riwayat')).text)
        b=await c.get(url+'?halaman_transfer=2&tab_detail=ringkasan')
        assert 'aria-labelledby="tab-ringkasan" >' in b.text
        assert '5.790 kg' in b.text
        assert (await c.get(url+'?tab_detail=bahan&kembali_kerja=https://jahat.example')).status_code==200
        assert 'href="https://jahat.example"' not in b.text


async def test_penghalang_tidak_memblokir_tutup_bobot_sama(pg,pabrik):
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.web import csrf
    pid=await _minta(pg,pabrik)
    await _acc(pg,pabrik,pid,tujuan='A',berat=6000)
    p=await _kirim(pg,pabrik,pid,berat=6000)
    async with pg() as db:
        await mulai_penyosohan(db,user=await db.get(User,pabrik['op2']),nama_silos=['A'])
    async with await _klien(pg,peran='admin') as c:
        c.headers[csrf.NAMA_HEADER]=cap_formulir(c)
        r=await _potret(c,f'/riwayat-transfer/{p.internal_transfer_id}','terhalang')
        assert 'buka=tutup_permintaan_pk' in r.text
        assert 'Periksa catatan hilir' in r.text
        assert 'name="hasil_transfer"' not in r.text
        before=await _saldo(pg,pabrik['proses_id'])
        assert (await c.post('/api/actions/tutup-permintaan-pk',json={'permintaan':str(pid),'berat':5900})).status_code==400
        assert await _saldo(pg,pabrik['proses_id'])==before
        assert (await c.post('/api/actions/tutup-permintaan-pk',json={'permintaan':str(pid),'berat':6000})).status_code==200
        assert await _saldo(pg,pabrik['proses_id'])==before


@pytest.mark.parametrize('keadaan',['ditolak','gugur'])
async def test_keputusan_akhir_dan_data_permintaan_lama(pg,pabrik,keadaan):
    pid=await _minta(pg,pabrik)
    async with pg() as db:
        if keadaan=='ditolak':
            await permintaan_pk.tolak(db,user=await db.get(User,pabrik['admin']),permintaan_id=pid,sebab='Tujuan belum dapat dipakai <uji>')
        else:
            await transfer.create_internal_transfer(db,user=await db.get(User,pabrik['admin']),kode_proses=pabrik['lot'],lokasi_tujuan='ditumpuk',berat=None)
            await permintaan_pk.gugurkan_yang_habis(db)
        p=await db.get(PermintaanPk,pid)
        p.berat_minta_kg=None
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        r=await _potret(c,f'/permintaan-pk/{pid}',keadaan)
        assert keadaan.capitalize() in r.text
        assert 'Belum tercatat' in r.text and 'Belum terbentuk' in r.text
        assert 'buka=acc_permintaan_pk' not in r.text and 'buka=kirim_permintaan_pk' not in r.text
        if keadaan=='ditolak':assert 'Tujuan belum dapat dipakai &lt;uji&gt;' in r.text

async def test_operator_g1_melihat_tutup_terkunci_dan_post_tetap_ditolak(pg,pabrik):
    from bs4 import BeautifulSoup
    from tests.pg.formulir import cap_formulir
    pid=await _minta(pg,pabrik,berat=1000)
    await _acc(pg,pabrik,pid,berat=1000)
    await _kirim(pg,pabrik,pid,berat=1000)
    async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        page=await c.get(f'/permintaan-pk/{pid}')
        assert page.status_code==200
        soup=BeautifulSoup(page.text,'html.parser')
        controls=soup.select('[data-aksi-permintaan="tutup_permintaan_pk"]')
        assert controls
        assert all(n.get('aria-disabled')=='true' and not n.has_attr('href') for n in controls)
        assert (await c.post('/api/actions/tutup-permintaan-pk',json={'permintaan':str(pid),'berat':1000})).status_code==403
    assert (await _status(pg,pid))[0]=='dikirim'
    for role in ('admin','superadmin'):
        async with await _klien(pg,peran=role) as c:
            soup=BeautifulSoup((await c.get(f'/permintaan-pk/{pid}')).text,'html.parser')
            controls=soup.select('[data-aksi-permintaan="tutup_permintaan_pk"]')
            assert controls and all(n.name=='a' and 'buka=tutup_permintaan_pk' in n.get('href','') for n in controls)
