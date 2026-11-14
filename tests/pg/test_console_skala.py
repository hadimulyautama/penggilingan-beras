"""Pagination/filter Console tetap membaca saja, termasuk di atas batas lama 200."""
import pytest
from hmu_core import User,KeanggotaanPerusahaan
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from app.services import keanggotaan as svc
from tests.pg.test_console_monitoring import orang
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_pengaturan_organisasi import fakta

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]

async def test_pagination_seluruh_anggota_filter_username_dan_tidak_ada_mutasi(pg,orang):
    x=orang
    async with pg() as db:
        pw=(await db.get(Akun,x['aid'])).password_hash
        for i in range(215):
            u=User(nama=f'Anggota Skala {i:03}',role=P.OPERATOR,status='aktif');db.add(u);await db.flush()
            db.add(KeanggotaanPerusahaan(company_id=x['cid'],user_id=u.id,peran='admin' if i%10==0 else 'operator',aktif=i%7!=0))
            db.add(Akun(user_id=u.id,username=f'skala-{i:03}',password_hash=pw,status='aktif',token_version=1))
        await db.commit()
    before=await fakta(pg);ruang=svc.RuangAdministrasi(x['root'])
    async with pg() as db:
        seen=set()
        for n in range(1,9):
            d=await svc.rincian(db,ruang=ruang,company_id=x['cid'],halaman_anggota=n)
            assert d['anggota_total']==216 and d['anggota_hasil']==216 and d['anggota_halaman_total']==8
            ids={m['user_id'] for m in d['anggota']};assert not seen&ids;seen|=ids
            assert len(d['anggota'])<=30 and len(d['pengguna'])<=30
        assert len(seen)==216
        search=await svc.rincian(db,ruang=ruang,company_id=x['cid'],cari_pengguna='skala-214',halaman_anggota=1)
        assert search['anggota_hasil']==1 and search['anggota'][0]['username']=='skala-214'
        assert search['pengguna_total']==1
        filtered=await svc.rincian(db,ruang=ruang,company_id=x['cid'],halaman_anggota=1,peran_anggota='admin',status_anggota='aktif')
        assert 0<filtered['anggota_hasil']<22 and all(m['peran']=='admin' and m['aktif'] for m in filtered['anggota'])
        empty=await svc.rincian(db,ruang=ruang,company_id=x['cid'],halaman_anggota=999,cari_pengguna='Tidak tersedia')
        assert empty['anggota_halaman']==1 and empty['anggota_hasil']==0
        literal=await svc.rincian(db,ruang=ruang,company_id=x['cid'],halaman_anggota=1,cari_pengguna='%')
        assert literal['anggota_hasil']==0
        other=await svc.rincian(db,ruang=ruang,company_id=x['asing'],halaman_anggota=1)
        assert other['anggota_total']==0 and not other['anggota']
    assert await fakta(pg)==before

async def test_filter_tidak_valid_ditolak_dan_api_lama_tetap_200(pg,orang):
    from app.services.organisasi_master import OrganisasiError
    ruang=svc.RuangAdministrasi(orang['root'])
    async with pg() as db:
        for fields in [dict(halaman_anggota=0),dict(peran_anggota='superadmin'),dict(status_anggota='lain'),dict(halaman_pengguna=-1),dict(lokasi_anggota=-1)]:
            with pytest.raises(OrganisasiError):await svc.rincian(db,ruang=ruang,company_id=orang['cid'],**fields)
        d=await svc.rincian(db,ruang=ruang,company_id=orang['cid'])
        assert d['anggota'][0]['user_id']==orang['uid']

async def test_direktori_filter_koneksi_sortir_dan_read_only(pg,orang,monkeypatch):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.test_console_akses import sesi
    from app.config import settings
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        assert (await c.get('/internal/console/perusahaan?urut=nama')).status_code==401
        headers=await sesi(c);before=await fakta(pg)
        for sort in ('nama','terbaru','anggota'):
            r=await c.get('/internal/console/perusahaan?urut='+sort,headers=headers)
            assert r.status_code==200 and r.json()['total']==2
            if sort=='anggota':assert r.json()['perusahaan'][0]['id']==orang['cid']
        r=await c.get('/internal/console/perusahaan?layanan=lokal',headers=headers)
        assert r.status_code==200 and [d['id'] for d in r.json()['perusahaan']]==[orang['cid']]
        assert r.json()['perusahaan'][0]['layanan']=='lokal'
        r=await c.get('/internal/console/perusahaan?layanan=registry',headers=headers)
        assert [d['id'] for d in r.json()['perusahaan']]==[orang['asing']]
        r=await c.get(f"/internal/console/perusahaan/{orang['cid']}?halaman_anggota=1&status_anggota=aktif",headers=headers)
        assert r.status_code==200 and r.json()['anggota_total']==1
        assert (await c.get('/internal/console/perusahaan?urut=tidak-valid',headers=headers)).status_code==422
        assert await fakta(pg)==before
