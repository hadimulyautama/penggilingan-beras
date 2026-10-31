"""Pintu perbaikan tetap memakai rantai stok, audit, dan izin lama."""
import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select, func

from app.database import now_local
from app.models import ActivityLog, OutgoingItem, OutgoingRecord, User
from app.services import barang_keluar as bk
from tests.pg.formulir import cap_formulir
from tests.pg.test_barang_keluar import gudang, _klien, _perintah, _stok
from tests.pg.test_retur_pengajuan import asal, simpan

pytestmark = pytest.mark.asyncio


async def selesai(pg, g):
    h = await _perintah(pg, g, karung=4)
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, g['op']), rec_id=h.rec.id)
        await bk.verifikasi(db, user=await db.get(User, g['adm']), rec_id=h.rec.id)
    return h.rec.id


async def log_terakhir(pg):
    async with pg() as db:
        return await db.scalar(select(ActivityLog).where(ActivityLog.table_name == 'outgoing_records',
            ActivityLog.dibatalkan_pada.is_(None)).order_by(ActivityLog.id.desc()).limit(1))


async def post(c, rid, logid, **kw):
    return await c.post(f'/api/actions/perbaikan-pengiriman/{rid}/buka-ulang',
        json=dict(log_id=logid, alasan='Koreksi kesalahan pencatatan yang telah diperiksa', konfirmasi=True, **kw),
        headers={'X-CSRF-Token':cap_formulir(c)})


async def test_baca_perbaikan_tidak_mengubah_stok_status_audit_dan_filter(pg, gudang):
    rid = await selesai(pg, gudang)
    async with pg() as db:
        n = await db.scalar(select(func.count()).select_from(ActivityLog))
    async with await _klien(pg, gudang['adm'], 'perbaiki-baca') as c:
        for url in [f'/barang-keluar/{rid}', '/barang-keluar',
                    f'/barang-keluar/{rid}/perbaikan?q=uji&status=selesai&sebelum=42']:
            r = await c.get(url)
            assert r.status_code == 200, r.text
            assert 'Perbaiki pengiriman' in r.text
        assert 'q=uji&amp;status=selesai&amp;sebelum=42' in r.text
        assert 'Jumlah atau barang salah' in r.text and 'Pelanggan atau kiriman salah' in r.text
        assert 'Buka kembali verifikasi kiriman' in r.text and f'data-log="{(await log_terakhir(pg)).id}"' in r.text
    assert await _stok(pg, gudang) == 9900
    async with pg() as db:
        assert (await db.get(OutgoingRecord, rid)).status == 'selesai'
        assert await db.scalar(select(func.count()).select_from(ActivityLog)) == n


async def test_buka_ulang_terikat_log_tidak_ganda_audit_alasan_dan_pembatalan_lama(pg, gudang):
    rid = await selesai(pg, gudang); log = await log_terakhir(pg)
    async with await _klien(pg, gudang['adm'], 'perbaiki-tulis') as c:
        assert (await post(c, rid, log.id)).status_code == 200
        assert (await post(c, rid, log.id)).status_code == 409
        assert await _stok(pg, gudang) == 9900  # membuka verifikasi tidak memulihkan stok
        page = await c.get(f'/barang-keluar/{rid}/perbaikan')
        assert 'Batalkan langkah selesai muat' in page.text
        assert 'buka=pilih_tiket_armada' in page.text and 'buka=koreksi_plat_pengiriman' in page.text
        assert (await post(c, rid, (await log_terakhir(pg)).id)).status_code == 200
        page = await c.get(f'/barang-keluar/{rid}/perbaikan')
        assert 'Koreksi total muatan' in page.text and 'Periksa pembatalan' in page.text
        assert 'Buat perintah pengganti' not in page.text
        async with pg() as db:
            await bk.batalkan(db, user=await db.get(User,gudang['adm']), rec_id=rid, sebab='Pelanggan yang dipilih salah')
        page = await c.get(f'/barang-keluar/{rid}/perbaikan')
        assert 'Buat perintah pengganti' in page.text
    assert await _stok(pg, gudang) == 10000  # hanya isian Muat semua dibalik
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        assert rec.status == 'batal'
        original = await db.get(ActivityLog, log.id)
        assert original.dibatalkan_pada and original.dibatalkan_oleh == gudang['adm']
        audits = (await db.scalars(select(ActivityLog).where(ActivityLog.table_name == 'undo'))).all()
        assert len(audits) == 2 and all(a.alasan_perubahan for a in audits)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord)) == 1


async def test_log_kiriman_lain_dan_snapshot_lama_ditolak(pg, gudang):
    rid = await selesai(pg, gudang); old = await log_terakhir(pg)
    second = await selesai(pg, gudang); new = await log_terakhir(pg)
    async with await _klien(pg,gudang['adm'],'perbaiki-basi') as c:
        assert (await post(c, rid, new.id)).status_code == 409
        assert (await post(c, rid, old.id)).status_code == 409
    assert await _stok(pg,gudang) == 9800
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rid)).status == 'selesai'
        assert (await db.get(OutgoingRecord,second)).status == 'selesai'


async def test_batas_48_jam_dan_konfirmasi_tetap_dijaga(pg,gudang):
    rid = await selesai(pg,gudang); log = await log_terakhir(pg)
    async with await _klien(pg,gudang['adm'],'perbaiki-batas') as c:
        bad = await c.post(f'/api/actions/perbaikan-pengiriman/{rid}/buka-ulang',
            json={'log_id':log.id,'alasan':'   ','konfirmasi':True},headers={'X-CSRF-Token':cap_formulir(c)})
        assert bad.status_code == 400
        payload={'log_id':log.id,'alasan':'Periksa data','konfirmasi':False}
        assert (await c.post(f'/api/actions/perbaikan-pengiriman/{rid}/buka-ulang',json=payload,
            headers={'X-CSRF-Token':cap_formulir(c)})).status_code==400
        payload['konfirmasi']=True
        assert (await c.post(f'/api/actions/perbaikan-pengiriman/{rid}/buka-ulang',json=payload)).status_code==403
        async with pg() as db:
            for item in (await db.scalars(select(ActivityLog))).all():
                item.waktu_perubahan=now_local()-timedelta(hours=50)+timedelta(seconds=item.id)
            await db.commit()
        page=await c.get(f'/barang-keluar/{rid}/perbaikan')
        assert 'Lewat batas 48 jam' in page.text and 'data-perbaikan-pengiriman' not in page.text
        assert (await post(c,rid,log.id)).status_code == 409
    assert await _stok(pg,gudang) == 9900


async def test_retur_aktif_menahan_buka_ulang(pg,asal):
    await simpan(pg,asal,2)
    # Catatan verifikasi fixture tidak mempunyai audit langkah; tambahkan
    # log sah sebagai tindakan terakhir, lalu biarkan layanan lama menolaknya.
    from app.services.activity_log import log_activity
    async with pg() as db:
        await log_activity(db,table_name='outgoing_records',record_id=asal['oid'],action='UPDATE',
            changed_by=asal['uid'],aksi='barang_keluar_verifikasi',new_value='Verifikasi uji')
        await db.commit()
    log=await log_terakhir(pg)
    async with await _klien(pg,asal['uid'],'perbaiki-retur') as c:
        page=await c.get(f'/barang-keluar/{asal["oid"]}/perbaikan')
        assert 'memiliki retur terkait' in page.text
        r=await post(c,asal['oid'],log.id)
        assert r.status_code==409 and 'retur terkait' in r.text


@pytest.mark.parametrize('lihat',[None,'operator:g1','operator:g2'])
async def test_izin_endpoint_dan_mode_lihat_sebagai(pg,gudang,lihat):
    rid=await selesai(pg,gudang); log=await log_terakhir(pg)
    uid=gudang['op'] if lihat is None else gudang['adm']
    if lihat:
        async with pg() as db:
            (await db.get(User,uid)).role='superadmin';await db.commit()
    async with await _klien(pg,uid,'perbaiki-akses',mode='operator' if lihat is None else 'superadmin') as c:
        if lihat:
            r=await c.post('/lihat-sebagai',data={'peran':lihat,'_csrf':cap_formulir(c)})
            assert r.status_code==303
        assert (await c.get(f'/barang-keluar/{rid}/perbaikan')).status_code==403
        assert (await post(c,rid,log.id)).status_code==403
    assert await _stok(pg,gudang)==9900


async def test_dua_permohonan_bersamaan_hanya_membalik_sekali(pg,gudang):
    rid=await selesai(pg,gudang);log=await log_terakhir(pg)
    async with await _klien(pg,gudang['adm'],'perbaiki-balapan') as c:
        a,b=await asyncio.gather(post(c,rid,log.id),post(c,rid,log.id))
        assert sorted([a.status_code,b.status_code])==[200,409]
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='undo'))==1
    assert await _stok(pg,gudang)==9900


@pytest.mark.parametrize('retur_aktif',[False,True])
async def test_kiriman_gabungan_buka_seluruhnya_atau_tidak_sama_sekali(pg,asal,retur_aktif):
    from tests.pg.test_riwayat_kiriman import gabung
    from app.services.activity_log import log_activity
    oid,_,_=await gabung(pg,asal)
    if retur_aktif:await simpan(pg,asal,2)
    async with pg() as db:
        await log_activity(db,table_name='outgoing_records',record_id=oid,action='UPDATE',
            changed_by=asal['uid'],aksi='barang_keluar_verifikasi',new_value='Verifikasi gabungan uji')
        await db.commit()
        before={i.id:float(i.berat_kg) for i in (await db.scalars(select(OutgoingItem))).all()}
    log=await log_terakhir(pg)
    async with await _klien(pg,asal['uid'],'perbaiki-gabungan') as c:
        page=await c.get(f'/barang-keluar/{oid}/perbaikan')
        assert 'Berlaku untuk seluruh pelanggan' in page.text
        assert 'Pelanggan pertama' in page.text and 'Rahasia pelanggan kedua' in page.text
        result=await post(c,oid,log.id)
        assert result.status_code==(409 if retur_aktif else 200),result.text
    async with pg() as db:
        records=(await db.scalars(select(OutgoingRecord))).all()
        assert all(r.status==('selesai' if retur_aktif else 'dimuat') for r in records)
        assert {i.id:float(i.berat_kg) for i in (await db.scalars(select(OutgoingItem))).all()}==before
        assert bool((await db.get(ActivityLog,log.id)).dibatalkan_pada)==(not retur_aktif)


async def test_perintah_jasa_historis_tidak_diarahkan_ke_penjualan_pabrik(pg,asal):
    from app.models import Jasa
    async with pg() as db:
        jasa=Jasa(kode='JAS-LEGACY-PERBAIKAN',pelanggan_id=asal['pid'])
        db.add(jasa);await db.flush()
        rec=await db.get(OutgoingRecord,asal['oid']);rec.jasa_id=jasa.id;rec.status='batal'
        await db.commit()
    async with await _klien(pg,asal['uid'],'perbaiki-jasa-historis') as c:
        page=await c.get(f'/barang-keluar/{asal["oid"]}/perbaikan')
        assert page.status_code==200
        assert 'href="/barang-keluar/pengambilan-jasa"' in page.text
        assert 'href="/barang-keluar/baru"' not in page.text
