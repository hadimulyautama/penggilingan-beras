"""Pengajuan dan pengaitan tiket saja; tidak ada penulisan stok/penyelesaian.

Transaksi dimiliki endpoint. Savepoint mencegah pemanggil meninggalkan
pengajuan separuh bila pencatatan audit/penyisipan salah satu item gagal.
Kunci saldo bersama dan baris sumber menutup balapan alokasi serta tiket.
"""
import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

from sqlalchemy import select, text
from hmu_identitas import peran as P, pintu
from app.database import now_local
from app.models import User, Warehouse, Supplier, PkGudang2Intake
from app.models.retur_supplier import ReturSupplier, ReturSupplierItem
from app.services import barang_keluar as keluar
from app.services import retur_supplier_sumber as sumber
from app.services.activity_log import log_activity
from app.services.codegen import next_retur_supplier_code
from app.services.retur import angka

D = lambda v: Decimal(str(v))


def sidik(*data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()


async def pelaku(db, user, *, tulis=False, gudang=None):
    diminta=user.role
    gudang_diminta=getattr(user,'default_warehouse_id',None)
    # Baca kolom, bukan memuat ulang objek User input. Objek input dapat
    # membawa role efektif; populate_existing akan menimpanya dengan Admin.
    with db.no_autoflush:
        asli = (await db.execute(select(User.id,User.role,User.status).where(User.id==user.id))).first()
    if not asli or asli.status!='aktif' or not pintu.boleh_masuk(asli.role,pintu.PRODUKSI):
        raise PermissionError('Akun tidak memiliki akses PadiFlow yang aktif.')
    # Akun request membawa peran efektif. Jangan menaikkan kembali seorang
    # Admin yang sedang melihat sebagai Operator, atau mempercayai spoof role.
    efektif = P.peran_efektif(asli.role,diminta)
    if tulis=='muat' and not (P.admin_keatas(efektif) or P.operator_saja(efektif)):
        raise PermissionError('Pencatatan aktual dan barang keluar mengikuti izin kerja gudang.')
    if tulis and tulis!='muat' and not P.admin_keatas(efektif):
        raise PermissionError('Pengajuan, pengaitan, dan pembatalan Retur ke Supplier mengikuti izin Admin penerimaan retur.')
    if not P.admin_keatas(efektif):
        wh = await db.get(Warehouse,gudang_diminta) if gudang_diminta else None
        if not P.operator_saja(efektif) or not wh or not wh.aktif or (gudang and wh.kode_fungsi!=gudang):
            raise PermissionError('Rincian berada di luar gudang aktif akun.')
    return SimpleNamespace(id=asli.id,role=efektif,default_warehouse_id=gudang_diminta)


async def siapkan(db, tid, user, *, kecuali=None, kunci=False,izin=None):
    tulis='muat' if kunci and izin=='muat' else kunci
    await pelaku(db,user,tulis=tulis)
    meta=(await db.execute(text('SELECT jenis_kode FROM timbangan_transaksi WHERE id=:id AND arah=\'MASUK\''),{'id':tid})).first()
    if not meta:raise ValueError('Penerimaan Barang Masuk tidak ditemukan.')
    whkode='g1' if sumber.barang_masuk.jenis_tiket(meta.jenis_kode).startswith('gabah') else 'g2'
    await pelaku(db,user,tulis=tulis,gudang=whkode)
    if kunci:
        await keluar._kunci_saldo_keluar(db)
        # Urutan yang sama dengan pemindahan/muat PK: intake dahulu, batch
        # kemudian. Tiket sudah menjadi sumber tunggal metadata penerimaan.
        if sumber.barang_masuk.jenis_tiket(meta.jenis_kode)=='pk':
            await db.execute(select(PkGudang2Intake.id).where(PkGudang2Intake.tujuan=='ditumpuk').order_by(PkGudang2Intake.id).with_for_update())
    t,rows = await sumber.penerimaan(db,tid,kunci=kunci)
    opsi=await sumber.pilihan(db,t,rows,kecuali=kecuali)
    return t,opsi


def _isian(jumlah, alasan, catatan):
    if not isinstance(jumlah,list) or not jumlah:
        raise ValueError('Pilih setidaknya satu barang dari penerimaan asal.')
    if not isinstance(alasan,str) or (catatan is not None and not isinstance(catatan,str)):
        raise ValueError('Alasan dan catatan harus berupa teks.')
    alasan=alasan.strip();catatan=(catatan or '').strip()
    if not alasan:raise ValueError('Alasan retur wajib diisi; spasi saja tidak cukup.')
    if len(alasan)>2000 or len(catatan)>4000:raise ValueError('Alasan atau catatan terlalu panjang.')
    keys=[x.get('kunci') for x in jumlah if isinstance(x,dict)]
    if len(keys)!=len(jumlah) or any(not isinstance(x,str) for x in keys) or len(set(keys))!=len(keys):
        raise ValueError('Setiap sumber hanya boleh dipilih satu kali.')
    return jumlah,alasan,catatan


async def periksa(db, tid, user, jumlah, alasan, catatan=None, *, kunci=False, kecuali=None):
    jumlah,alasan,catatan=_isian(jumlah,alasan,catatan)
    t,opsi=await siapkan(db,tid,user,kunci=kunci,kecuali=kecuali)
    pilihan={x['kunci']:x for x in opsi};hasil=[];anggaran={}
    for j in jumlah:
        item=pilihan.get(j['kunci'])
        if not item:raise ValueError('Barang tidak termasuk penerimaan asal; pilih sumber yang ditampilkan.')
        if item['alasan_tidak_bisa']:raise ValueError(item['kode']+': '+item['alasan_tidak_bisa'])
        n=angka(j.get('jumlah'),'Jumlah retur',1_000_000,'1' if item['satuan']=='karung' else '.01')
        if n<=0:raise ValueError(item['kode']+': jumlah retur harus positif.')
        if n>item['maksimum']:raise ValueError(item['kode']+': saldo berubah atau jumlah melebihi batas retur terbaru.')
        if item['satuan']=='karung' and item['_jenis']=='pk':
            from app.penggilingan.gudang2.karung import bobot_per_karung
            berat=bobot_per_karung(item['_row'],jumlah=n).quantize(D('.00000001'),rounding=ROUND_HALF_UP)
        elif item['satuan']=='karung' and item['_jenis']=='beras':
            from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
            berat=berat_karung_nyata(item['_row'],int(n))
        else:
            berat=(n*item['per_kg']).quantize(D('.01'),rounding=ROUND_HALF_UP)
        if berat<=0:raise ValueError('Bobot pengajuan belum dapat dihitung dengan benar.')
        if item['_batas_pool'] is not None:
            key=item['_pool'];sisa=anggaran.setdefault(key,item['_batas_pool'])
            toleransi=D('.000001') if item['_jenis']=='pk' else D(0)
            if berat>sisa+toleransi:raise ValueError('Pemakaian gabungan sumber melebihi saldo yang belum dialokasikan.')
            anggaran[key]-=berat
        if item['_tambahan_pool']:
            key,batas=item['_tambahan_pool'];sisa=anggaran.setdefault(key,batas)
            if berat>sisa:raise ValueError('Pemakaian gabungan hasil samping melebihi saldo tersedia.')
            anggaran[key]-=berat
        hasil.append(dict(item,jumlah=n,bobot_kg=berat,
                          proyeksi_sisa_kg=max(D(0),item['tersedia_kg']-berat)))
    # Snapshot pemeriksaan, bukan izin menulis. Semua ID, jumlah, peran, stok,
    # dan alokasi tetap diperiksa ulang oleh periksa(..., kunci=True).
    dasar=sidik(t['id'],t['supplier_id'],t['status_transaksi'],[(x['kunci'],x['warehouse_id'],
        x['satuan'],x['per_kg'],x['stok_kg'],x['terikat_kg'],x['maksimum'],x['tersedia_kg'],x['_batas_pool'],x['_tambahan_pool']) for x in hasil])
    return dict(penerimaan=t,items=hasil,alasan=alasan,catatan=catatan,dasar=dasar,
        total_kg=sum((x['bobot_kg'] for x in hasil),D(0)),
        total_karung=sum((int(x['jumlah']) for x in hasil if x['satuan']=='karung'),0),
        total_curah_kg=sum((x['bobot_kg'] for x in hasil if x['satuan']=='kg'),D(0)))


def _normal_payload(tid, uid, jumlah, alasan, catatan):
    return sidik(tid,uid,sorted((x['kunci'],format(angka(x.get('jumlah'),'Jumlah retur',1_000_000,'.01').normalize(),'f')) for x in jumlah),alasan,catatan)


async def simpan(db, *, user, tid, jumlah, alasan, catatan, kunci, dasar):
    jumlah,alasan,catatan=_isian(jumlah,alasan,catatan)
    await pelaku(db,user,tulis=True)
    if not isinstance(kunci,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',kunci):
        raise ValueError('Kunci pengajuan tidak sah; buka kembali formulir sumber.')
    payload=_normal_payload(tid,user.id,jumlah,alasan,catatan)
    async with db.begin_nested():
        await keluar._kunci_saldo_keluar(db)
        lama=await db.scalar(select(ReturSupplier).where(ReturSupplier.kunci==kunci))
        if lama:
            if lama.sidik!=payload or lama.input_by!=user.id:
                raise ValueError('Kunci sudah dipakai dengan isian berbeda. Periksa pengajuan yang tersimpan.')
            return lama
        data=await periksa(db,tid,user,jumlah,alasan,catatan,kunci=True)
        if not dasar or dasar!=data['dasar']:
            raise ValueError('Sumber atau saldo berubah setelah diperiksa. Baca data terbaru dan periksa ulang; isian dipertahankan.')
        t=data['penerimaan'];now=now_local()
        rec=ReturSupplier(kode=await next_retur_supplier_code(db),penerimaan_tiket_id=tid,
            supplier_id=t['supplier_id'],status='diajukan',alasan=alasan,catatan=catatan or None,
            sumber=dict(kode_tiket=t['kode'],supplier=t['nama_supplier'],nota=t['nota'],
                        waktu=str(t['timbang1_waktu']) if t['timbang1_waktu'] else None),
            kunci=kunci,sidik=payload,input_by=user.id,waktu=now)
        db.add(rec);await db.flush()
        audit=[]
        for x in data['items']:
            snap={k:str(x[k]) if isinstance(x[k],Decimal) else x[k] for k in (
                'kode','nama','pemilik','gudang','lokasi','diterima_kg','diterima_jumlah',
                'stok_kg','stok_jumlah','terikat_kg','per_kg','proyeksi_sisa_kg')}
            it=ReturSupplierItem(retur_supplier_id=rec.id,kunci_sumber=x['kunci'],
                **{sumber.FK[x['_jenis']]:x['_row'].id},warehouse_id=x['warehouse_id'],
                jumlah=x['jumlah'],satuan=x['satuan'],bobot_kg=x['bobot_kg'],
                tipe_pool=x['tipe_pool'],product_sku_id=x.get('product_sku_id'),
                rice_quality_standard_id=x.get('rice_quality_standard_id'),jenis_produk=x.get('jenis_produk'),snapshot=snap)
            db.add(it);audit.append(dict(sumber=x['kunci'],jumlah=str(x['jumlah']),satuan=x['satuan'],kg=str(x['bobot_kg'])))
        await db.flush()
        await log_activity(db,table_name='retur_supplier',record_id=rec.id,action='INSERT',
            changed_by=user.id,aksi='retur_supplier_ajukan',alasan=alasan,
            new_value=json.dumps(dict(kode=rec.kode,penerimaan=tid,supplier_id=rec.supplier_id,items=audit)))
        return rec


async def ambil(db, identitas, user, *, kunci=False,izin=None):
    tulis='muat' if kunci and izin=='muat' else kunci
    await pelaku(db,user,tulis=tulis)
    q=select(ReturSupplier).where(ReturSupplier.id==identitas).execution_options(populate_existing=True)
    rec=await db.scalar(q.with_for_update() if kunci else q)
    if not rec:raise ValueError('Pengajuan retur tidak ditemukan.')
    items=(await db.scalars(select(ReturSupplierItem).where(ReturSupplierItem.retur_supplier_id==rec.id).order_by(ReturSupplierItem.id))).all()
    if not items:raise ValueError('Rincian pengajuan belum lengkap; periksa hubungan sumber.')
    for wid in {x.warehouse_id for x in items}:
        wh=await db.get(Warehouse,wid)
        if not wh:raise PermissionError('Gudang pengajuan perlu diperiksa.')
        await pelaku(db,user,tulis=tulis,gudang=wh.kode_fungsi)
    return rec,items


async def tiket(db, tid, *, kunci=False):
    sql='SELECT * FROM timbangan_transaksi WHERE id=:id'
    if kunci and db.get_bind().dialect.name=='postgresql':sql+=' FOR UPDATE'
    row=(await db.execute(text(sql),{'id':tid})).mappings().first()
    return dict(row) if row else None


def syarat_tiket(t, rec):
    if (not t or t['arah']!='RETUR_KELUAR' or t['jenis_kode']!='RETUR_SUPPLIER'
        or t['supplier_id']!=rec.supplier_id or t['status_transaksi']!='AKTIF'
        or t['status_tiket'] not in ('TERBUKA','SELESAI') or t['id']==rec.penerimaan_tiket_id):
        raise ValueError('Pilih tiket Retur ke Supplier aktif milik supplier penerimaan yang sama.')
    if t['timbang1_kg'] is None or angka(t['timbang1_kg'],'Timbang pertama',1_000_000,'.001')<=0:
        raise ValueError('Tiket belum memiliki timbang pertama yang sah.')
    if t['status_tiket']=='SELESAI' and (t['timbang2_kg'] is None or
            angka(t['timbang2_kg'],'Timbang kedua',1_000_000,'.001')<=0 or t['berat_barang_kg'] is None):
        raise ValueError('Hasil tiket selesai belum lengkap; periksa data TeraFlow.')


async def hubungkan(db, *, user, identitas, tiket_id):
    await pelaku(db,user,tulis=True)
    async with db.begin_nested():
        await keluar._kunci_saldo_keluar(db)
        rec,items=await ambil(db,identitas,user,kunci=True)
        if rec.status!='diajukan':raise ValueError('Pengajuan sudah dibatalkan.')
        t=await tiket(db,tiket_id,kunci=True);syarat_tiket(t,rec)
        lain=await db.scalar(select(ReturSupplier.id).where(ReturSupplier.timbangan_transaksi_id==tiket_id,ReturSupplier.id!=rec.id))
        if lain:raise ValueError('Tiket sudah digunakan pengajuan retur lain, termasuk riwayat batal.')
        if rec.timbangan_transaksi_id:
            if rec.timbangan_transaksi_id!=tiket_id:raise ValueError('Tiket sudah terhubung; penggantian diam-diam tidak diperbolehkan.')
            return rec
        data=await periksa(db,rec.penerimaan_tiket_id,user,
            [dict(kunci=x.kunci_sumber,jumlah=str(x.jumlah)) for x in items],
            rec.alasan,rec.catatan,kunci=True,kecuali=rec.id)
        baru={x['kunci']:x for x in data['items']}
        if any(baru[x.kunci_sumber]['bobot_kg']!=x.bobot_kg for x in items):
            raise ValueError('Bobot partai berubah dari pengajuan. Periksa data atau batalkan dan ajukan ulang secara sah.')
        rec.timbangan_transaksi_id=tiket_id;rec.tiket_dihubungkan_oleh=user.id;rec.tiket_dihubungkan_pada=now_local()
        await db.flush()
        await log_activity(db,table_name='retur_supplier',record_id=rec.id,action='UPDATE',
            field_name='timbangan_transaksi_id',changed_by=user.id,aksi='retur_supplier_tautkan',
            new_value=json.dumps(dict(tiket_id=tiket_id,kode=t['kode'],supplier_id=rec.supplier_id)))
        return rec


async def batalkan(db, *, user, identitas, alasan):
    await pelaku(db,user,tulis=True)
    alasan=(alasan or '').strip()
    if not alasan:raise ValueError('Alasan pembatalan wajib diisi.')
    async with db.begin_nested():
        await keluar._kunci_saldo_keluar(db)
        rec,items=await ambil(db,identitas,user,kunci=True)
        if rec.status=='dibatalkan':return rec
        if rec.status!='diajukan':raise ValueError('Barang keluar sudah tercatat. Pembatalan pengajuan tidak boleh memulihkan stok historis; gunakan koreksi yang berwenang.')
        rec.status='dibatalkan';rec.dibatalkan_oleh=user.id;rec.dibatalkan_pada=now_local();rec.alasan_batal=alasan
        await log_activity(db,table_name='retur_supplier',record_id=rec.id,action='UPDATE',
            field_name='status',old_value='diajukan',new_value='dibatalkan',changed_by=user.id,
            aksi='retur_supplier_batalkan',alasan=alasan)
        await db.flush();return rec
