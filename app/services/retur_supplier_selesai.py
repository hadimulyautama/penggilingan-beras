"""Pemeriksaan versi data dan satu pencatatan keluar melalui buku peristiwa.

Semua mutasi memakai kunci saldo lama + kunci sumber + transaksi pemanggil.
GET hanya membaca; periksa, manual, dan keluar adalah perintah eksplisit.
"""
import json
from datetime import datetime
from decimal import Decimal as D
from sqlalchemy import select,text
from app.database import now_local
from app.models import ProductSku,KemasanTara,PackageSize,User
from app.models.retur_supplier import (ReturSupplierItem as Item,ReturSupplierAktual as Aktual,
    ReturSupplierPemeriksaan as Pemeriksaan,ReturSupplierKeluar as Keluar)
from app.services import retur_supplier as s,peristiwa as buku
from app.services.activity_log import log_activity
from app.services.retur_pemeriksaan import BarisBobot,periksa_bobot


def bersih(v):
    return json.loads(json.dumps(v,default=lambda x:format(x.normalize(),'f') if isinstance(x,D) else str(x)))


def versi_tiket(t):
    return s.sidik(*[(k,t.get(k)) for k in ('id','kode','arah','jenis_kode','supplier_id','status_tiket',
        'status_transaksi','jumlah_revisi','updated_at','timbang1_kg','timbang2_kg',
        'timbang1_waktu','timbang2_waktu','berat_barang_kg','total_tara_kg','tara_lain_kg')])


def bobot_tiket(t):
    return {k:str(t.get(k)) for k in ('timbang1_kg','timbang2_kg','berat_barang_kg')}


async def data(db,identitas,user,*,kunci=False):
    rec,items=await s.ambil(db,identitas,user,kunci=kunci,izin='muat')
    hasil=await db.scalar(select(Keluar).where(Keluar.retur_supplier_id==rec.id))
    aktual={a.item_id:a for a in (await db.scalars(select(Aktual).where(Aktual.item_id.in_([i.id for i in items])))).all()}
    tiket=await s.tiket(db,rec.timbangan_transaksi_id,kunci=kunci) if rec.timbangan_transaksi_id else None
    asal,opsi=await s.siapkan(db,rec.penerimaan_tiket_id,user,kecuali=rec.id,kunci=kunci,izin='muat') if not hasil else (None,[])
    if asal and asal['supplier_id']!=rec.supplier_id:raise ValueError('Supplier penerimaan berubah dari pengajuan. Periksa hubungan sumber dan riwayat koreksinya sebelum melanjutkan.')
    choices=(await db.execute(select(KemasanTara,PackageSize.ukuran_kg).join(PackageSize))).all()
    return rec,items,aktual,tiket,{x['kunci']:x for x in opsi},hasil,choices


async def _rincian(db,rec,items,aktual,t,opsi,jumlah,user):
    if not t:raise ValueError('Hubungkan tiket Retur ke Supplier terlebih dahulu.')
    s.syarat_tiket(t,rec)
    if t['status_tiket']!='SELESAI':raise ValueError('Tiket belum selesai timbang kedua.')
    final=s.angka(t['berat_barang_kg'],'Hasil akhir tiket',1_000_000,'.001')
    if final<=0:raise ValueError('Hasil akhir tiket belum sah.')
    if not isinstance(jumlah,list) or len(jumlah)!=len(items):raise ValueError('Rincian aktual harus mencakup semua item pengajuan.')
    byid={x.get('item_id'):x for x in jumlah if isinstance(x,dict)}
    if len(byid)!=len(items) or set(byid)!={i.id for i in items}:raise ValueError('Item aktual bukan bagian dari pengajuan ini.')
    if any(i.kunci_sumber not in opsi for i in items):raise ValueError('Hubungan sumber pengajuan berubah atau penerimaan tidak lagi tersedia. Periksa riwayat sumber sebelum melanjutkan.')
    for i in items:
        x=opsi[i.kunci_sumber]
        if (x['satuan']!=i.satuan or x['warehouse_id']!=i.warehouse_id or x.get('product_sku_id')!=i.product_sku_id
            or x.get('rice_quality_standard_id')!=i.rice_quality_standard_id or x.get('jenis_produk')!=i.jenis_produk):
            raise ValueError('Satuan, gudang, atau identitas produk berubah dari pengajuan. Periksa sumber dan koreksi yang sah terlebih dahulu.')
    positif=[];nilai={};tara={}
    for i in items:
        raw=byid[i.id]
        if raw.get('jumlah') is None or not str(raw['jumlah']).strip():raise ValueError('Isi aktual setiap barang. Gunakan angka 0 untuk barang yang tidak ikut keluar.')
        n=s.angka(raw.get('jumlah'),'Jumlah aktual',1_000_000,'1' if i.satuan=='karung' else '.01')
        nilai[i.id]=n
        if n>0:positif.append(dict(kunci=i.kunci_sumber,jumlah=str(n)))
        if n>0 and i.satuan=='karung':
            o=opsi[i.kunci_sumber]
            if i.product_sku_id:
                sku=await db.get(ProductSku,i.product_sku_id)
                kt=await db.scalar(select(KemasanTara).where(KemasanTara.packaging_material_id==sku.packaging_material_id,KemasanTara.package_size_id==sku.package_size_id))
                if raw.get('kemasan_tara_id') not in (None,kt.id if kt else None):raise ValueError('Kemasan aktual berbeda dari identitas SKU asal.')
            else:
                kid=raw.get('kemasan_tara_id') or (aktual[i.id].kemasan_tara_id if i.id in aktual else None)
                kt=await db.get(KemasanTara,kid) if kid else None
                ukuran=getattr(o['_row'],'ukuran_karung_kg',None)
                if kt and ukuran is not None:
                    ps=await db.get(PackageSize,kt.package_size_id)
                    if ps.ukuran_kg!=ukuran:raise ValueError('Ukuran kemasan harus sesuai partai asal.')
            if kt is None or kt.tara_per_karung_kg is None:raise ValueError('Tara kemasan aktual belum tersedia. Lengkapi data kemasan yang sah sebelum pemeriksaan.')
            tr=s.angka(kt.tara_per_karung_kg,'Tara per karung',1_000,'.0001')
            if tr<=0:raise ValueError('Tara kemasan aktual belum sah; lengkapi master kemasan sebelum pemeriksaan.')
            tara[i.id]=(kt.id,tr)
        else:tara[i.id]=(None,D(0))
    if not positif:raise ValueError('Minimal satu barang harus benar-benar keluar. Seluruh aktual nol tidak dapat diselesaikan.')
    diperiksa=await s.periksa(db,rec.penerimaan_tiket_id,user,positif,rec.alasan,rec.catatan,kecuali=rec.id)
    return diperiksa,nilai,tara,final


async def _audit(db,rec,user,aksi,old=None,new=None,alasan=None):
    await log_activity(db,table_name='retur_supplier',record_id=rec.id,action='UPDATE',changed_by=user.id,
        aksi=aksi,old_value=json.dumps(bersih(old)) if old is not None else None,
        new_value=json.dumps(bersih(new)) if new is not None else None,alasan=alasan)


async def _siapkan_pemeriksaan(db,identitas,user,jumlah):
    await s.pelaku(db,user,tulis='muat')
    await s.keluar._kunci_saldo_keluar(db)
    rec,items,aktual,t,opsi,hasil,_=await data(db,identitas,user,kunci=True)
    if hasil or rec.status!='diajukan':raise ValueError('Pengajuan tidak lagi dapat diperiksa atau dicatat keluar.')
    # _rincian menggunakan service periksa yang sama; identitas efektif
    # dikirim secara eksplisit untuk mencegah pewarisan hak pengaju lama.
    calc,nilai,tara,final=await _rincian(db,rec,items,aktual,t,opsi,jumlah,user)
    hitung={x['kunci']:x for x in calc['items']};rincian=[]
    for i in items:
        x=opsi[i.kunci_sumber];n=nilai[i.id];kg=hitung[i.kunci_sumber]['bobot_kg'] if n>0 else D(0)
        if n>0 and x['stok_kg'] is None:raise ValueError('Stok fisik belum dapat dipastikan.')
        sebelum=x['stok_kg'];sesudah=sebelum-kg if sebelum is not None else None
        if i.pk_purchase_batch_id and sesudah is not None and -D('.000001')<=sesudah<0:sesudah=D(0)
        if sesudah is not None and sesudah<0:raise ValueError('Stok fisik tidak mencukupi; periksa saldo terbaru.')
        bebas=x['tersedia_kg'];lain=x['terikat_kg']
        rincian.append(dict(item_id=i.id,kunci=i.kunci_sumber,kode=x['kode'],nama=x['nama'],gudang=x['gudang'],pemilik=x['pemilik'],lokasi=x['lokasi'],
            satuan=i.satuan,pengajuan=i.jumlah,pengajuan_kg=i.bobot_kg,jumlah=n,bobot_kg=kg,
            stok_sebelum_kg=sebelum,stok_sesudah_kg=sesudah,karung_sebelum=x['stok_jumlah'] if i.satuan=='karung' else None,
            karung_sesudah=x['stok_jumlah']-n if i.satuan=='karung' and x['stok_jumlah'] is not None else None,
            alokasi_sendiri_kg=i.bobot_kg,alokasi_lain_kg=lain,
            alokasi_tidak_keluar_kg=max(D(0),i.bobot_kg-kg),tambahan_bebas_kg=max(D(0),kg-i.bobot_kg),
            tersedia_sesudah_kg=max(D(0),bebas-kg) if bebas is not None else None,kemasan_tara_id=tara[i.id][0],tara_per_karung_kg=tara[i.id][1],
            tara_kg=n*tara[i.id][1] if i.satuan=='karung' else D(0)))
    pembanding=periksa_bobot([BarisBobot(x['bobot_kg'],int(x['jumlah']) if x['satuan']=='karung' else 0,x['tara_per_karung_kg'])
        for x in rincian if x['bobot_kg']>0],tiket_selesai=True,berat_tiket_kg=final,pernah_selisih_besar=rec.wajib_manual)
    if pembanding.toleransi_kg is None or pembanding.selisih_kg is None:raise ValueError(pembanding.alasan)
    total=pembanding.berat_rincian_kg;toleransi=pembanding.toleransi_kg;beda=pembanding.selisih_kg
    snap=bersih(dict(items=rincian,total_kg=total,tiket_id=t['id'],kode_tiket=t['kode'],revisi_tiket=t.get('jumlah_revisi',0),
        versi_tiket=versi_tiket(t),bobot_tiket=bobot_tiket(t),hasil_kg=final,selisih_kg=beda,toleransi_kg=toleransi,dasar_sumber=calc['dasar']))
    snap['dasar']=s.sidik(snap)
    return rec,items,aktual,t,snap


async def periksa(db,*,identitas,user,jumlah,alasan=''):
    if len(alasan)>2000:raise ValueError('Alasan koreksi maksimal 2.000 karakter.')
    async with db.begin_nested():
        rec,items,lama,t,snap=await _siapkan_pemeriksaan(db,identitas,user,jumlah)
        before=[dict(item_id=i.id,jumlah=str(lama[i.id].jumlah if i.id in lama else i.jumlah),
            bobot_kg=str(lama[i.id].bobot_kg if i.id in lama else i.bobot_kg),
            kemasan_tara_id=lama[i.id].kemasan_tara_id if i.id in lama else None,
            tara_per_karung_kg=str(lama[i.id].tara_per_karung_kg) if i.id in lama else None) for i in items]
        changed=any(D(x['jumlah'])!=D(old['jumlah']) or D(x['bobot_kg'])!=D(old['bobot_kg']) or
            (old['kemasan_tara_id'] is not None and (old['kemasan_tara_id']!=x['kemasan_tara_id'] or old['tara_per_karung_kg'] is None or D(old['tara_per_karung_kg'])!=D(x['tara_per_karung_kg']))) for x,old in zip(snap['items'],before))
        if changed and not (alasan or '').strip():raise ValueError('Jumlah aktual berbeda; alasan koreksi berdasarkan pemeriksaan fisik wajib diisi.')
        if changed or not lama:
            rec.versi_aktual+=1
            for x in snap['items']:
                a=lama.get(x['item_id']) or Aktual(item_id=x['item_id'])
                a.jumlah=D(x['jumlah']);a.bobot_kg=D(x['bobot_kg']);a.kemasan_tara_id=x['kemasan_tara_id'];a.tara_per_karung_kg=D(x['tara_per_karung_kg'])
                db.add(a)
            await _audit(db,rec,user,'retur_supplier_aktual',before,snap['items'],(alasan or '').strip() or None)
        now=now_local();snap.update(versi_aktual=rec.versi_aktual,waktu=now.isoformat())
        if abs(D(snap['selisih_kg']))>D(snap['toleransi_kg']):
            rec.wajib_manual=True
            # Terakhir di luar batas menjadi dasar koreksi, bukan hanya
            # selisih pertama yang mungkin sudah pernah dikoreksi sebelumnya.
            rec.dasar_selisih_besar=bersih(dict(versi_aktual=rec.versi_aktual,bobot_tiket=bobot_tiket(t),
                revisi_tiket=t.get('jumlah_revisi',0),waktu=now.isoformat(),aktual=[(x['item_id'],x['jumlah'],x['bobot_kg']) for x in snap['items']]))
            rec.verifikasi=None;status='perlu_koreksi'
        elif rec.wajib_manual:
            rec.verifikasi=None;status='siap_manual' if await koreksi_sah(db,rec,t,snap) else 'perlu_koreksi'
        else:
            status='terverifikasi_otomatis';rec.verifikasi=bersih(dict(snap,metode='otomatis',oleh=user.id))
        snap['status']=status
        db.add(Pemeriksaan(retur_supplier_id=rec.id,versi_aktual=rec.versi_aktual,status=status,snapshot=snap,input_by=user.id,waktu=now))
        await _audit(db,rec,user,'retur_supplier_periksa',new=snap)
        await db.flush()
        return snap


async def koreksi_sah(db,rec,t,snap):
    dasar=rec.dasar_selisih_besar
    if not dasar:return False
    aktual=[(x['item_id'],x['jumlah'],x['bobot_kg']) for x in snap['items']]
    if rec.versi_aktual>dasar['versi_aktual'] and bersih(aktual)!=dasar['aktual']:return True
    if int(t.get('jumlah_revisi') or 0)<=int(dasar['revisi_tiket']) or bobot_tiket(t)==dasar['bobot_tiket']:return False
    if not await db.scalar(text("SELECT to_regclass('timbangan_audit')")):return False
    logs=(await db.execute(text("SELECT nilai_sebelum,nilai_sesudah FROM timbangan_audit WHERE aksi='KOREKSI' AND entitas='transaksi' AND entitas_id=:kode AND waktu>:waktu"),
        dict(kode=t['kode'],waktu=datetime.fromisoformat(dasar['waktu'])))).all()
    for a,b in logs:
        try:
            a=json.loads(a or '{}');b=json.loads(b or '{}')
            if any(k in a and k in b and str(a[k])!=str(b[k]) for k in ('timbang1_kg','timbang2_kg','berat_barang_kg')):return True
        except (ValueError,TypeError):continue
    return False


async def _terbaru(db,rec):
    return await db.scalar(select(Pemeriksaan).where(Pemeriksaan.retur_supplier_id==rec.id).order_by(Pemeriksaan.id.desc()).limit(1))


async def manual(db,*,identitas,user,dasar,catatan,konfirmasi):
    if not (catatan or '').strip() or konfirmasi is not True:raise ValueError('Catatan hasil dan konfirmasi pemeriksaan koreksi wajib diisi.')
    if len(catatan)>2000:raise ValueError('Catatan verifikasi maksimal 2.000 karakter.')
    async with db.begin_nested():
        await s.pelaku(db,user,tulis=True);await s.keluar._kunci_saldo_keluar(db)
        rec,items,aktual,t,_,hasil,_=await data(db,identitas,user,kunci=True)
        last=await _terbaru(db,rec)
        if hasil or not rec.wajib_manual or not last or last.status!='siap_manual':raise ValueError('Koreksi dan pemeriksaan ulang yang sah diperlukan sebelum manual.')
        _,_,_,_,snap=await _siapkan_pemeriksaan(db,identitas,user,[dict(item_id=i.id,jumlah=str(aktual[i.id].jumlah),kemasan_tara_id=aktual[i.id].kemasan_tara_id) for i in items])
        if not dasar or dasar!=last.snapshot['dasar'] or dasar!=snap['dasar'] or not await koreksi_sah(db,rec,t,snap):raise ValueError('Data berubah; baca hasil terbaru dan periksa ulang sebelum verifikasi manual.')
        snap.update(versi_aktual=rec.versi_aktual,metode='manual',oleh=user.id,waktu=now_local().isoformat(),catatan=catatan.strip())
        rec.verifikasi=bersih(snap)
        db.add(Pemeriksaan(retur_supplier_id=rec.id,versi_aktual=rec.versi_aktual,status='terverifikasi_manual',snapshot=bersih(snap),input_by=user.id,waktu=now_local()))
        await _audit(db,rec,user,'retur_supplier_verifikasi_manual',new=snap,alasan=catatan.strip());await db.flush()
        return snap


async def catat_keluar(db,*,identitas,user,dasar,konfirmasi):
    if konfirmasi is not True:raise ValueError('Konfirmasikan barang aktual benar-benar sudah keluar dari gudang.')
    async with db.begin_nested():
        await s.pelaku(db,user,tulis='muat');await s.keluar._kunci_saldo_keluar(db)
        rec,items,aktual,t,_,hasil,_=await data(db,identitas,user,kunci=True)
        if hasil:
            if hasil.snapshot.get('dasar')!=dasar:raise ValueError('Pengajuan sudah dicatat dengan pemeriksaan berbeda. Buka riwayat barang keluar.')
            return hasil
        v=rec.verifikasi
        if not v or rec.status!='diajukan' or not dasar or dasar!=v['dasar']:raise ValueError('Verifikasi terbaru yang sah diperlukan sebelum mencatat keluar.')
        _,_,_,_,snap=await _siapkan_pemeriksaan(db,identitas,user,[dict(item_id=i.id,jumlah=str(aktual[i.id].jumlah),kemasan_tara_id=aktual[i.id].kemasan_tara_id) for i in items])
        if snap['dasar']!=dasar or rec.versi_aktual!=v['versi_aktual']:raise ValueError('Saldo, rincian aktual, atau revisi tiket berubah. Belum ada barang keluar; periksa ulang sebelum konfirmasi.')
        if abs(D(snap['selisih_kg']))>D(snap['toleransi_kg']) or (rec.wajib_manual and v['metode']!='manual'):raise ValueError('Pemeriksaan koreksi dan verifikasi manual masih diperlukan.')
        from app.services.codegen import next_retur_supplier_keluar_code
        kode=await next_retur_supplier_keluar_code(db)
        muatan=bersih(dict(snap,kode=kode,retur_supplier_id=rec.id,verifikasi=v,penerimaan_tiket_id=rec.penerimaan_tiket_id,supplier_id=rec.supplier_id))
        e=await buku.catat(db,jenis='retur_supplier_keluar',pelaku_id=user.id,kunci_kiriman=f'retur_supplier_keluar:{rec.id}',muatan=muatan)
        rec.status='selesai_gudang';await db.flush()
        await _audit(db,rec,user,'retur_supplier_keluar',new=muatan)
        return await db.get(Keluar,e.id)
