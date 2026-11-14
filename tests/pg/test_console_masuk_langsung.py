"""Kredensial lama -> sesi Console, hanya database loopback uji."""
import secrets
from unittest.mock import patch
import pytest
from pydantic import SecretStr
from sqlalchemy import select,func
from hmu_identitas import peran as P,masuk as identitas,sandi as S
from hmu_identitas.model import Akun
from app.config import settings
from app.models import SesiConsole
from app.web import gerbang_masuk as gerbang
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_pengaturan_organisasi import fakta

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]
KEY='kunci-login-console-hanya-untuk-pengujian-1234567890'
HEADERS={'X-Console-Login-Key':KEY}


@pytest.fixture(autouse=True)
def konfigurasi(monkeypatch):
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    monkeypatch.setattr(settings,'console_login_secret',SecretStr(KEY))
    from app.services.console_pembatas import pembatas
    gerbang.bersihkan();pembatas.bersihkan()
    yield
    gerbang.bersihkan();pembatas.bersihkan()


async def data_masuk(pg):
    async with pg() as db:
        a=await db.scalar(select(Akun).order_by(Akun.id.desc()))
        return dict(username=a.username,sandi='rahasia123',jejak='a'*64)


async def kirim(c,data,headers=HEADERS):return await c.post('/internal/console/masuk',json=data,headers=headers)


async def test_akun_super_lama_masuk_tanpa_cookie_pf_dan_tanpa_transaksi_berubah(pg):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        data=await data_masuk(pg);c.cookies.clear()
        before=await fakta(pg)
        async with pg() as db:
            a=await db.scalar(select(Akun));account=(a.password_hash,a.token_version,a.status,a.harus_ganti_sandi,a.user.role,a.user.status)
        r=await kirim(c,data);assert r.status_code==200,r.text
        assert len(r.json()['token'])==64 and r.json()['berlaku_detik']==3600
        assert 'no-store' in r.headers['cache-control']
        from app.web.security import NAMA_COOKIE
        assert NAMA_COOKIE not in r.cookies
        token=r.json()['token'];h={'Authorization':'Bearer '+token}
        assert (await c.get('/internal/console/saya',headers=h)).status_code==200
        after=await fakta(pg)
        assert {k:v for k,v in before.items() if k not in ('hmu_console_sessions','produksi_akun')}=={k:v for k,v in after.items() if k not in ('hmu_console_sessions','produksi_akun')}
        async with pg() as db:
            a=await db.scalar(select(Akun));assert (a.password_hash,a.token_version,a.status,a.harus_ganti_sandi,a.user.role,a.user.status)==account
            row=await db.scalar(select(SesiConsole));assert row.token_hash!=token and row.ditukar_pada and a.terakhir_login
        assert (await c.post('/internal/console/keluar',headers=h,json={})).status_code==200
        assert (await c.get('/internal/console/saya',headers=h)).status_code==401


@pytest.mark.parametrize('role',[P.ADMIN,P.OPERATOR])
async def test_peran_lain_tetap_ditolak_meski_sandinya_benar(pg,role):
    async with await _klien(pg,peran=role) as c:
        data=await data_masuk(pg);before=await fakta(pg)
        for _ in range(6):
            r=await kirim(c,data);assert r.status_code==403 and r.json()['detail']['kode']=='peran'
        assert await fakta(pg)==before


@pytest.mark.parametrize('field',['status_akun','status_user','wajib_sandi'])
async def test_nonaktif_dan_wajib_ganti_sandi_tidak_dapat_sesi(pg,field):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        data=await data_masuk(pg)
        async with pg() as db:
            a=await db.scalar(select(Akun))
            if field=='status_akun':a.status='nonaktif'
            elif field=='status_user':a.user.status='nonaktif'
            else:a.harus_ganti_sandi=True
            await db.commit()
        before=await fakta(pg);r=await kirim(c,data)
        assert r.status_code==403
        assert r.json()['detail']['kode']==('wajib_sandi' if field=='wajib_sandi' else 'nonaktif')
        assert await fakta(pg)==before


async def test_kunci_klien_diperiksa_sebelum_validasi_badan_dan_sandi(pg,monkeypatch):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        data=await data_masuk(pg);before=await fakta(pg)
        r=await c.post('/internal/console/masuk',content='sandi=JANGAN-BOCOR',headers={'Content-Type':'application/json'})
        assert r.status_code==403 and 'JANGAN-BOCOR' not in r.text
        assert (await kirim(c,data,{'X-Console-Login-Key':'salah'})).status_code==403
        monkeypatch.setattr(settings,'console_login_secret',SecretStr(''))
        assert (await kirim(c,data)).status_code==503
        assert await fakta(pg)==before


async def test_validasi_dan_log_tidak_memantulkan_sandi(pg,caplog):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        data=await data_masuk(pg);before=await fakta(pg)
        secret='RAHASIA-INPUT-UJI-JANGAN-BOCOR'
        for value in (secret*100,{'isi':secret}):
            r=await kirim(c,{**data,'sandi':value})
            assert r.status_code==422 and secret not in r.text
        r=await kirim(c,{**data,'sandi':secret,'role':P.SUPERADMIN})
        assert r.status_code==422 and secret not in r.text
        assert secret not in caplog.text
        assert await fakta(pg)==before


async def test_salah_dan_nama_tidak_ada_pesan_sama_cookie_pf_bukan_pengganti_sandi(pg):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        data=await data_masuk(pg);before=await fakta(pg)
        r=await kirim(c,{**data,'sandi':'SALAH-UJI'})
        other=await kirim(c,{**data,'username':'tidak-terdaftar'})
        assert r.status_code==other.status_code==401 and r.json()==other.json()
        assert await fakta(pg)==before


async def test_pembatasan_per_jejak_dan_pembukaan_ulang_mengikuti_generasi(pg):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        data=await data_masuk(pg)
        for _ in range(5):assert (await kirim(c,{**data,'sandi':'salah'})).status_code==401
        r=await kirim(c,data);assert r.status_code==429 and int(r.headers['retry-after'])>0
        # Sumber lain tetap dapat masuk tanpa memutus sesi aplikasi harian.
        assert (await kirim(c,{**data,'jejak':'b'*64})).status_code==200
        gerbang.pakai_generasi(data['username'],17)
        assert (await kirim(c,data)).status_code==200


@pytest.mark.parametrize('field',['peran','versi','status','wajib'])
async def test_pencabutan_terbaru_tetap_berlaku_setelah_login_langsung(pg,field):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        r=await kirim(c,await data_masuk(pg));assert r.status_code==200
        h={'Authorization':'Bearer '+r.json()['token']}
        async with pg() as db:
            a=await db.scalar(select(Akun))
            if field=='peran':a.user.role=P.OPERATOR
            elif field=='versi':a.token_version+=1
            elif field=='status':a.user.status='nonaktif'
            else:a.harus_ganti_sandi=True
            await db.commit()
        assert (await c.get('/internal/console/saya',headers=h)).status_code==401


async def test_reset_sandi_di_tengah_verifikasi_tidak_menerbitkan_sesi_baru(pg):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        data=await data_masuk(pg);original=identitas.periksa_kredensial
        async def reset(db,uname,password):
            a=await original(db,uname,password)
            async with pg() as other:
                b=await other.get(Akun,a.id);b.password_hash=S.hash_sandi('sandi-baru-uji');b.token_version+=1;await other.commit()
            return a
        with patch.object(identitas,'periksa_kredensial',side_effect=reset):r=await kirim(c,data)
        assert r.status_code==401
        async with pg() as db:assert await db.scalar(select(func.count()).select_from(SesiConsole))==0


async def test_semprot_nama_berbeda_tetap_dibatasi_per_sumber(pg):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        data=await data_masuk(pg)
        for n in range(20):assert (await kirim(c,{**data,'username':'tidak-ada-'+str(n)})).status_code==401
        r=await kirim(c,data);assert r.status_code==429 and r.json()['detail']['kode']=='sibuk'
        assert (await kirim(c,{**data,'jejak':'b'*64})).status_code==200
