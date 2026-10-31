"""Koreksi terverifikasi memakai stok efektif lama, jejak tambah-saja."""
import asyncio
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select,func,text
from app.database import now_local
from app.models import ActivityLog,FinishedGoodsStock,Jasa,KoreksiPengiriman,OutgoingItem,OutgoingRecord,User
from app.services import barang_keluar as bk,koreksi_pengiriman as svc
from tests.pg.test_barang_keluar import gudang,_perintah,_stok,_klien,_tiket
from tests.pg.test_pengambilan_jasa_halaman import dunia,saldo
from tests.pg.test_retur_pengajuan import asal,simpan as pengajuan
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio


async def completed(pg,g,karung=20):
    h=await _perintah(pg,g,karung=karung)
    async with pg() as db:
        await bk.muat_semua(db,user=await db.get(User,g['op']),rec_id=h.rec.id)
        await bk.verifikasi(db,user=await db.get(User,g['adm']),rec_id=h.rec.id)
    return h.rec.id


async def request(pg,rid,*,jumlah=None,pelanggan=None,pilih=None,sebab=''):
    async with pg() as db:
        rec=await db.get(OutgoingRecord,rid)
        items=(await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==rid).order_by(OutgoingItem.id))).all()
        rows=[]
        for i in items:
            n=(jumlah.get(i.id) if isinstance(jumlah,dict) else jumlah)
            if n is None:n=i.jumlah_karung if i.item_type=='finished_goods' else i.berat_kg
            rows.append(dict(item_id=i.id,pilih=(pilih.get(i.id,'') if isinstance(pilih,dict) else pilih) or await svc.pilihan(db,i),jumlah=str(n)))
        return dict(pelanggan_id=pelanggan or rec.pelanggan_id,barang=rows,alasan='Koreksi kesalahan pencatatan berdasarkan pemeriksaan fisik dan dokumen',sebab_selisih=sebab,konfirmasi=True)


async def preview(pg,rid,uid,req):
    async with pg() as db:
        _,_,plan=await svc.rencana(db,rid,await db.get(User,uid),req)
        return plan,svc.cap(plan)


async def apply(pg,rid,uid,req,token,key=None):
    async with pg() as db:
        result=await svc.simpan(db,rid,await db.get(User,uid),req,dasar=token,kunci=key or uuid4().hex)
        await db.commit();return result


async def test_lama_bukan_input_terakhir_tetap_bisa_dikoreksi_beruntun(pg,gudang):
    rid=await completed(pg,gudang)
    async with pg() as db:
        rec=await db.get(OutgoingRecord,rid)
        old_time=now_local()-timedelta(days=30)
        rec.waktu=rec.waktu_perintah=rec.waktu_muat=rec.waktu_verifikasi=old_time
        rec.tanggal=old_time.date()
        original=(rec.waktu_verifikasi,rec.diverifikasi_oleh,rec.status)
        for log in (await db.scalars(select(ActivityLog))).all():log.waktu_perubahan=now_local()-timedelta(days=30)
        await db.commit()
    other=await _perintah(pg,gudang,karung=10,pembeli='Pelanggan lain yang lebih baru')
    assert await _stok(pg,gudang)==9500
    req=await request(pg,rid,jumlah=18);plan,token=await preview(pg,rid,gudang['adm'],req)
    assert await _stok(pg,gudang)==9500
    assert plan['sumber'][0]['delta_kg']==-50
    first=await apply(pg,rid,gudang['adm'],req,token)
    assert first.versi==1 and await _stok(pg,gudang)==9550
    req=await request(pg,rid,jumlah=19);_,token=await preview(pg,rid,gudang['adm'],req)
    second=await apply(pg,rid,gudang['adm'],req,token)
    assert second.versi==2 and await _stok(pg,gudang)==9525
    async with pg() as db:
        rec=await db.get(OutgoingRecord,rid)
        assert (rec.waktu_verifikasi,rec.diverifikasi_oleh,rec.status)==original
        assert (await db.get(OutgoingRecord,other.rec.id)).status=='perintah'
        assert first.snapshot['barang'][0]['sebelum']['berat_kg']=='500.00'
        assert second.snapshot['barang'][0]['sebelum']['berat_kg']=='450.00'
        original_logs=(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='outgoing_records',ActivityLog.record_id==rid))).all()
        assert all(l.dibatalkan_pada is None for l in original_logs)
        with pytest.raises(bk.BarangKeluarError,match='koreksi pascaverifikasi'):await bk.balik_verifikasi(db,rec_id=rid)
    async with await _klien(pg,gudang['adm'],'uji-koreksi-selesai') as c:
        page=await c.get(f'/barang-keluar/{rid}')
        assert page.status_code==200 and 'koreksi 2' in page.text.lower()
        page=await c.get(f'/barang-keluar/{rid}/koreksi-selesai')
        assert page.status_code==200 and 'Tidak dibatasi input terakhir atau 48 jam' in page.text
    from app.services.pemeriksaan_pengiriman import baca
    async with pg() as db:
        status=await baca(db,await db.get(OutgoingRecord,rid))
        assert status['terverifikasi'] and 'koreksi manual tercatat' in status['status']
        from app.services.serah_terima import pengeluaran
        dokumen=await pengeluaran(db,rid)
        assert dokumen['total']=='475 kg' and 'koreksi pascaverifikasi v2' in dokumen['catatan']


async def test_reservasi_lain_dan_gagal_atomik_saldo_tidak_berubah(pg,gudang):
    rid=await completed(pg,gudang)
    await _perintah(pg,gudang,karung=300)
    req=await request(pg,rid,jumlah=150)
    with pytest.raises(ValueError,match='saldo bebas'):await preview(pg,rid,gudang['adm'],req)
    assert await _stok(pg,gudang)==9500
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(KoreksiPengiriman))==0


async def test_total_sumber_berulang_dijumlah_sebelum_mutasi(pg,gudang):
    rid=await completed(pg,gudang)
    async with pg() as db:
        old=await db.scalar(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==rid))
        extra=OutgoingItem(outgoing_record_id=rid,item_type=old.item_type,product_sku_id=old.product_sku_id,
            rice_quality_standard_id=old.rice_quality_standard_id,berat_kg=0,jumlah_karung=0,berat_perintah_kg=0)
        db.add(extra);await db.commit()
    req=await request(pg,rid,jumlah=300)
    with pytest.raises(ValueError,match='saldo bebas'):await preview(pg,rid,gudang['adm'],req)
    assert await _stok(pg,gudang)==9500


@pytest.mark.parametrize('nilai',['-1','1.5','NaN','Infinity','0'])
async def test_jumlah_tidak_sah_ditolak(pg,gudang,nilai):
    rid=await completed(pg,gudang);req=await request(pg,rid,jumlah=nilai)
    with pytest.raises((ValueError,bk.BarangKeluarError)):await preview(pg,rid,gudang['adm'],req)
    assert await _stok(pg,gudang)==9500


async def test_klik_ganda_idempoten_dan_koreksi_bersamaan_basi_ditolak(pg,gudang):
    rid=await completed(pg,gudang);req=await request(pg,rid,jumlah=18)
    _,token=await preview(pg,rid,gudang['adm'],req);key=uuid4().hex
    x,y=await asyncio.gather(apply(pg,rid,gudang['adm'],req,token,key),apply(pg,rid,gudang['adm'],req,token,key))
    assert x.kunci==y.kunci and await _stok(pg,gudang)==9550
    with pytest.raises(ValueError,match='berubah|Belum ada perubahan'):await apply(pg,rid,gudang['adm'],req,token)
    changed=await request(pg,rid,jumlah=17)
    with pytest.raises(ValueError,match='berbeda'):await apply(pg,rid,gudang['adm'],changed,token,key)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(KoreksiPengiriman))==1
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='koreksi_pengiriman_selesai'))==1


async def test_saldo_berubah_setelah_preview_memerlukan_konfirmasi_baru(pg,gudang):
    rid=await completed(pg,gudang);req=await request(pg,rid,jumlah=22)
    _,token=await preview(pg,rid,gudang['adm'],req)
    other=await _perintah(pg,gudang,karung=10)
    with pytest.raises(ValueError,match='berubah'):await apply(pg,rid,gudang['adm'],req,token)
    assert await _stok(pg,gudang)==9500
    _,new=await preview(pg,rid,gudang['adm'],req);await apply(pg,rid,gudang['adm'],req,new)
    assert await _stok(pg,gudang)==9450


async def test_retur_membatasi_jumlah_dan_melindungi_identitas(pg,asal):
    await pengajuan(pg,asal,3)
    req=await request(pg,asal['oid'],jumlah=2)
    with pytest.raises(ValueError,match='retur diterima'):await preview(pg,asal['oid'],asal['uid'],req)
    req=await request(pg,asal['oid'],jumlah=18)
    _,token=await preview(pg,asal['oid'],asal['uid'],req)
    await apply(pg,asal['oid'],asal['uid'],req,token)
    async with pg() as db:
        _,used=await __import__('app.services.retur_pengajuan',fromlist=['sisa_asal']).sisa_asal(db,asal['oid'])
        assert used[asal['iid']]['karung']==3


async def test_item_pelanggan_lain_tidak_bisa_disisipkan(pg,gudang):
    rid=await completed(pg,gudang);other=await completed(pg,gudang)
    req=await request(pg,rid,jumlah=18);outside=await request(pg,other,jumlah=18)
    req['barang'][0]['item_id']=outside['barang'][0]['item_id']
    with pytest.raises(ValueError,match='Seluruh item'):await preview(pg,rid,gudang['adm'],req)
    assert await _stok(pg,gudang)==9000


@pytest.mark.parametrize('role',['admin','superadmin','operator:g1','operator:g2'])
async def test_halaman_endpoint_izin_efektif_dan_get_baca_saja(pg,gudang,role):
    rid=await completed(pg,gudang)
    async with pg() as db:
        (await db.get(User,gudang['adm'])).role='superadmin';await db.commit()
        before=await db.scalar(select(func.count()).select_from(ActivityLog))
    async with await _klien(pg,gudang['adm'],'uji-koreksi-izin',mode='superadmin') as c:
        if role!='superadmin':
            response=await c.post('/lihat-sebagai',data={'peran':role,'_csrf':cap_formulir(c)})
            assert response.status_code==303
        permitted=role in ('admin','superadmin')
        assert (await c.get(f'/barang-keluar/{rid}/koreksi-selesai')).status_code==(200 if permitted else 403)
        req=await request(pg,rid,jumlah=18);body={**req,'kunci':uuid4().hex}
        response=await c.post(f'/api/actions/koreksi-pengiriman/{rid}/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
        assert response.status_code==(200 if permitted else 403),response.text
        if permitted:
            assert (await c.post(f'/api/actions/koreksi-pengiriman/{rid}/simpan',json={**body,'dasar':response.json()['dasar']})).status_code==403
    assert await _stok(pg,gudang)==9500
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityLog))==before
        assert await db.scalar(select(func.count()).select_from(KoreksiPengiriman))==0


async def test_tiket_satu_armada_ambang_manual_dan_revisi_basi(pg,gudang):
    rid=await completed(pg,gudang);tid=await _tiket(pg,'TK-KOREKSI',barang=500)
    async with pg() as db:
        (await db.get(OutgoingRecord,rid)).timbangan_transaksi_id=tid;await db.commit()
    req=await request(pg,rid,jumlah=16);plan,token=await preview(pg,rid,gudang['adm'],req)
    assert plan['pemeriksaan']['selisih_kg']==100 and not plan['pemeriksaan']['sebab_wajib']
    negative=await request(pg,rid,jumlah=24)
    other,_=await preview(pg,rid,gudang['adm'],negative)
    assert other['pemeriksaan']['selisih_kg']==-100 and not other['pemeriksaan']['sebab_wajib']
    req2=await request(pg,rid,jumlah=15)
    with pytest.raises(ValueError,match='sebab selisih'):await preview(pg,rid,gudang['adm'],req2)
    req2['sebab_selisih']='Kesalahan jumlah tercatat sudah diperiksa'
    await preview(pg,rid,gudang['adm'],req2)
    async with pg() as db:
        await db.execute(text('UPDATE timbangan_transaksi SET timbang2_kg=timbang2_kg+1 WHERE id=:id'),{'id':tid});await db.commit()
    with pytest.raises(ValueError,match='berubah'):await apply(pg,rid,gudang['adm'],req,token)
    assert await _stok(pg,gudang)==9500


async def test_pelanggan_nonjasa_salah_dikoreksi_tanpa_mutasi_stok(pg,gudang):
    from app.models import Pelanggan
    rid=await completed(pg,gudang)
    async with pg() as db:
        p=Pelanggan(nama_pelanggan='Penerima yang benar',kledo_contact_id=9933);db.add(p);await db.commit();pid=p.id
    req=await request(pg,rid,pelanggan=pid);plan,token=await preview(pg,rid,gudang['adm'],req)
    assert all(s['delta_kg']==0 for s in plan['sumber'])
    result=await apply(pg,rid,gudang['adm'],req,token)
    assert await _stok(pg,gudang)==9500
    async with pg() as db:
        rec=await db.get(OutgoingRecord,rid)
        assert rec.pelanggan_id==pid and rec.nama_pembeli=='Penerima yang benar' and rec.status=='selesai'
        assert result.snapshot['sebelum']['pelanggan_id']!=pid


async def test_koreksi_barang_nonjasa_ke_curah_memulihkan_sumber_asal_saja(pg,gudang):
    from app.models import Supplier
    from tests.pg.test_pk_g2_keluar import _masuk_tumpukan
    from app.penggilingan.gudang2.service import hitung_stok_tumpukan
    rid=await completed(pg,gudang)
    async with pg() as db:sid=await db.scalar(select(Supplier.id).limit(1))
    await _masuk_tumpukan(pg,gudang['op'],'PKB-KOREKSI-SUMBER',2000,None,sid)
    req=await request(pg,rid,jumlah='600.25',pilih='g2:tumpukan')
    _,token=await preview(pg,rid,gudang['adm'],req)
    result=await apply(pg,rid,gudang['adm'],req,token)
    assert await _stok(pg,gudang)==10000
    async with pg() as db:
        assert await hitung_stok_tumpukan(db,jasa_id=None)==1399.75
        i=await db.scalar(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==rid))
        assert i.item_type=='pk_g2' and i.product_sku_id is None and i.jumlah_karung==13
        assert result.snapshot['barang'][0]['sebelum']['item_type']=='finished_goods'
        assert (await db.get(OutgoingRecord,rid)).status=='selesai'


async def jasa_completed(pg,g,dua=False):
    d=await dunia(pg,g)
    async with pg() as db:
        stock=await db.scalar(select(FinishedGoodsStock));stock.jumlah_karung=200;stock.berat_total_kg=5000
        jid=d['jb']
        if dua:
            j=Jasa(kode='JAS-KOREKSI-02',pelanggan_id=d['a'],status='berjalan');db.add(j);await db.flush();jid=j.id
        db.add(FinishedGoodsStock(product_sku_id=stock.product_sku_id,rice_quality_standard_id=stock.rice_quality_standard_id,
            source_type=stock.source_type,source_id=stock.source_id,jumlah_karung=200,berat_total_kg=5000,
            warehouse_id=stock.warehouse_id,waktu=stock.waktu,input_by=stock.input_by,jasa_id=jid))
        await db.commit()
        bars=[bk.BarisPerintah(tipe='finished_goods',sku_id=g['sku'],std_id=g['std'],jumlah_karung=20,jasa_id=d['ja'])]
        if dua:bars.append(bk.BarisPerintah(tipe='finished_goods',sku_id=g['sku'],std_id=g['std'],jumlah_karung=10,jasa_id=jid))
        h=await bk.buat_perintah(db,user=await db.get(User,g['adm']),pelanggan_id=d['a'],baris=bars)
        await bk.muat_semua(db,user=await db.get(User,g['op']),rec_id=h.rec.id)
        await bk.verifikasi(db,user=await db.get(User,g['adm']),rec_id=h.rec.id)
        return d,h.rec.id,jid


async def test_jasa_dua_pesanan_selisih_tidak_menyentuh_pesanan_lain(pg,gudang):
    d,rid,jid=await jasa_completed(pg,gudang,True)
    async with pg() as db:
        items=(await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==rid).order_by(OutgoingItem.id))).all()
    req=await request(pg,rid,jumlah={items[0].id:18,items[1].id:10});_,token=await preview(pg,rid,gudang['adm'],req)
    await apply(pg,rid,gudang['adm'],req,token)
    assert await saldo(pg,gudang,d['ja'])==4550 and await saldo(pg,gudang,jid)==4750
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rid)).jasa_id is None
        assert {i.jasa_id for i in (await db.scalars(select(OutgoingItem))).all()}=={d['ja'],jid}


async def test_jasa_pelanggan_dan_sumber_salah_wajib_sesuai_pemilik(pg,gudang):
    d,rid,_=await jasa_completed(pg,gudang)
    wrong=await request(pg,rid,pelanggan=d['b'])
    with pytest.raises(ValueError,match='bukan milik'):await preview(pg,rid,gudang['adm'],wrong)
    req=await request(pg,rid,pelanggan=d['b'],pilih=f"bj:{gudang['sku']}|{gudang['std']}@{d['jb']}",jumlah=18)
    _,token=await preview(pg,rid,gudang['adm'],req)
    result=await apply(pg,rid,gudang['adm'],req,token)
    assert await saldo(pg,gudang,d['ja'])==5000 and await saldo(pg,gudang,d['jb'])==4550
    async with pg() as db:
        rec=await db.get(OutgoingRecord,rid);i=await db.scalar(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==rid))
        assert rec.pelanggan_id==d['b'] and i.jasa_id==d['jb']
        assert result.snapshot['barang'][0]['sebelum']['jasa_id']==d['ja']
    mixed=await request(pg,rid,pilih=f"bj:{gudang['sku']}|{gudang['std']}",jumlah=10)
    with pytest.raises(ValueError,match='tidak boleh dicampur'):await preview(pg,rid,gudang['adm'],mixed)


async def test_kiriman_gabungan_total_tiket_sekali_pelanggan_lain_tetap(pg,asal):
    from tests.pg.test_riwayat_kiriman import gabung
    from app.models import KirimanKeluar
    oid,iid,kid=await gabung(pg,asal);tid=await _tiket(pg,'TK-GABUNG-KOREKSI',barang=600)
    async with pg() as db:
        (await db.get(KirimanKeluar,kid)).timbangan_transaksi_id=tid;await db.commit()
    req=await request(pg,asal['oid'])
    req['barang'][0]['jumlah']='18'
    plan,token=await preview(pg,asal['oid'],asal['uid'],req)
    assert plan['pemeriksaan']['total_aktual_kg']==550 and plan['pemeriksaan']['selisih_kg']==50
    await apply(pg,asal['oid'],asal['uid'],req,token)
    async with pg() as db:
        assert (await db.get(OutgoingRecord,oid)).status=='selesai'
        assert float((await db.get(OutgoingItem,iid)).berat_kg)==100
        assert (await db.get(KirimanKeluar,kid)).timbangan_transaksi_id==tid


async def test_kegagalan_audit_membatalkan_seluruh_koreksi(pg,gudang,monkeypatch):
    rid=await completed(pg,gudang);req=await request(pg,rid,jumlah=18)
    _,token=await preview(pg,rid,gudang['adm'],req)
    async def gagal(*args,**kw):raise RuntimeError('Gangguan penyimpanan audit sintetis')
    monkeypatch.setattr(svc,'log_activity',gagal)
    with pytest.raises(RuntimeError,match='sintetis'):await apply(pg,rid,gudang['adm'],req,token)
    assert await _stok(pg,gudang)==9500
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(KoreksiPengiriman))==0
        assert float((await db.scalar(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==rid))).berat_kg)==500


async def test_retur_menahan_perubahan_sumber_dan_pelanggan(pg,asal):
    from app.models import Pelanggan
    await pengajuan(pg,asal,3)
    source=await request(pg,asal['oid'],pilih='cr:bekatul',jumlah=100)
    with pytest.raises(ValueError,match='jejak retur'):await preview(pg,asal['oid'],asal['uid'],source)
    async with pg() as db:
        p=Pelanggan(nama_pelanggan='Pelanggan berbeda',kledo_contact_id=9444);db.add(p);await db.commit();pid=p.id
    customer=await request(pg,asal['oid'],pelanggan=pid)
    with pytest.raises(ValueError,match='jejak retur'):await preview(pg,asal['oid'],asal['uid'],customer)


async def test_portal_setelah_koreksi_tetap_hanya_pemilik_yang_sah(pg,gudang):
    import httpx
    from app.main import app
    from app.models.portal import PortalAccount
    from app.web.portal.security import issue,COOKIE
    from app.web.security import hash_sandi
    d,rid,_=await jasa_completed(pg,gudang)
    req=await request(pg,rid,pelanggan=d['b'],pilih=f"bj:{gudang['sku']}|{gudang['std']}@{d['jb']}",jumlah=18)
    _,token=await preview(pg,rid,gudang['adm'],req);await apply(pg,rid,gudang['adm'],req,token)
    async with pg() as db:
        accounts=[]
        for pid in [d['a'],d['b']]:
            a=PortalAccount(username='portal-koreksi-'+str(pid),pelanggan_id=pid,password_hash=hash_sandi('uji-lokal'),active=True,token_version=1)
            db.add(a);accounts.append(a)
        await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        c.cookies.set(COOKIE,issue(accounts[0]))
        assert (await c.get(f'/pelanggan/barang-keluar/{rid}')).status_code==404
        c.cookies.set(COOKIE,issue(accounts[1]))
        page=await c.get(f'/pelanggan/barang-keluar/{rid}')
        assert page.status_code==200,page.text
        assert 'Pemilik A' not in page.text and 'Pemilik B' in page.text
        assert 'Koreksi pascaverifikasi' not in page.text
        assert (await c.get(f'/pelanggan/barang-keluar/{rid}/koreksi-selesai')).status_code in (403,404)


async def test_jasa_curah_1000_menjadi_998_hanya_memulihkan_selisih(pg,gudang):
    from app.models import Pelanggan
    from tests.pg.test_pk_g2_keluar import _masuk_tumpukan
    from app.penggilingan.gudang2.service import hitung_stok_tumpukan
    async with pg() as db:
        p=Pelanggan(nama_pelanggan='Pemilik curah koreksi',kledo_contact_id=9033);db.add(p);await db.flush()
        j=Jasa(kode='JAS-UJI-998',pelanggan_id=p.id,status='berjalan');db.add(j);await db.commit();pid=p.id;jid=j.id
    await _masuk_tumpukan(pg,gudang['op'],'PKB-KOR-998',2000,jid)
    async with pg() as db:
        h=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),pelanggan_id=pid,
            baris=[bk.BarisPerintah(tipe='pk_g2',berat_kg=1000,jasa_id=jid)])
        await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=h.rec.id)
        await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=h.rec.id)
    req=await request(pg,h.rec.id,jumlah='998.00');plan,token=await preview(pg,h.rec.id,gudang['adm'],req)
    assert plan['sumber'][0]['delta_kg']==-2
    await apply(pg,h.rec.id,gudang['adm'],req,token)
    async with pg() as db:
        assert await hitung_stok_tumpukan(db,jasa_id=jid)==1002
        item=await db.scalar(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==h.rec.id))
        assert item.jasa_id==jid and float(item.berat_kg)==998 and item.jumlah_karung==20


async def test_satu_item_nol_dan_item_lain_tetap_terkirim(pg,gudang):
    d,rid,jid=await jasa_completed(pg,gudang,True)
    async with pg() as db:
        items=(await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==rid).order_by(OutgoingItem.id))).all()
    req=await request(pg,rid,jumlah={items[0].id:0,items[1].id:10});_,token=await preview(pg,rid,gudang['adm'],req)
    await apply(pg,rid,gudang['adm'],req,token)
    assert await saldo(pg,gudang,d['ja'])==5000 and await saldo(pg,gudang,jid)==4750
    async with pg() as db:assert (await db.get(OutgoingRecord,rid)).status=='selesai'


async def test_retur_dan_koreksi_bersamaan_tidak_melampaui_jumlah_efektif(pg,asal):
    from app.services.retur_pengajuan import sisa_asal
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    req=await request(pg,asal['oid'],jumlah=2)
    _,token=await preview(pg,asal['oid'],asal['uid'],req)
    async with pg() as db:
        i=await db.get(OutgoingItem,asal['iid']);sku,std=i.product_sku_id,i.rice_quality_standard_id
        before=await hitung_stok_finished_goods(db,sku,std)
    outcomes=await asyncio.gather(apply(pg,asal['oid'],asal['uid'],req,token),pengajuan(pg,asal,3),return_exceptions=True)
    assert sum(isinstance(x,Exception) for x in outcomes)==1,outcomes
    async with pg() as db:
        item=await db.get(OutgoingItem,asal['iid']);_,used=await sisa_asal(db,asal['oid'])
        assert used[item.id]['karung']<=item.jumlah_karung
        after=await hitung_stok_finished_goods(db,sku,std)
        assert after['kg']==before['kg']+(450 if item.jumlah_karung==2 else 0)


async def test_retur_sudah_diterima_tidak_ditambah_stok_lagi_oleh_koreksi(pg,asal):
    from tests.pg.test_retur_pengajuan import selesai as selesai_retur,terima
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    application=await pengajuan(pg,asal,3)
    await selesai_retur(pg,asal,75)
    receipt=await terima(pg,application.id)
    assert receipt
    async with pg() as db:
        i=await db.get(OutgoingItem,asal['iid']);sku,std=i.product_sku_id,i.rice_quality_standard_id
        before=await hitung_stok_finished_goods(db,sku,std)
    bad=await request(pg,asal['oid'],jumlah=2)
    with pytest.raises(ValueError,match='retur diterima'):await preview(pg,asal['oid'],asal['uid'],bad)
    req=await request(pg,asal['oid'],jumlah=18);_,token=await preview(pg,asal['oid'],asal['uid'],req)
    key=uuid4().hex
    await apply(pg,asal['oid'],asal['uid'],req,token,key)
    await apply(pg,asal['oid'],asal['uid'],req,token,key)
    async with pg() as db:
        after=await hitung_stok_finished_goods(db,sku,std)
        assert after['kg']==before['kg']+50 and after['karung']==before['karung']+2
        from app.models import CustomerReturn
        assert await db.scalar(select(func.count()).select_from(CustomerReturn))==1
