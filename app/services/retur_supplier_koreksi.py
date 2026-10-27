"""Koreksi selisih sesudah keluar melalui ledger peristiwa yang sama.

Tidak commit. Seluruh pemeriksaan/simpan memakai kunci saldo lama, sumber
asli dan transaksi pemanggil; mutasi awal dan verifikasi awal tidak ditimpa.
"""
from datetime import datetime
from decimal import Decimal as D,ROUND_HALF_UP,InvalidOperation
from types import SimpleNamespace
import json,re
from sqlalchemy import select,text,func
from app.database import now_local
from app.models import ProductSku,KemasanTara,User
from app.models.retur_supplier import ReturSupplierAktual as A,ReturSupplierItem as I,ReturSupplierKeluar as K,ReturSupplierPemeriksaan as C
from app.models.retur_supplier_koreksi import ReturSupplierEfektif as E,ReturSupplierPerubahan as P,ReturSupplierDrafKoreksi as F
from app.services import retur_supplier as s,retur_supplier_selesai as f,retur_supplier_stok as stok,peristiwa as buku,retur_supplier_kembali as kembali
from app.services.activity_log import log_activity
from app.services.retur_pemeriksaan import periksa_bobot,BarisBobot


async def konteks(db,identitas,user,*,kunci=False):
    if kunci:await s.pelaku(db,user,tulis=True);await s.keluar._kunci_saldo_keluar(db)
    rec,items=await s.ambil(db,identitas,user,kunci=kunci)
    ledger=await db.scalar(select(K).where(K.retur_supplier_id==rec.id))
    if not ledger or rec.status!='selesai_gudang':raise ValueError('Tindakan ini hanya untuk retur yang sudah mencatat barang keluar.')
    state=await db.get(E,rec.id,populate_existing=kunci)
    rows=(await db.execute(select(I.id,stok.efektif('jumlah'),stok.efektif('bobot_kg')).join(A,A.item_id==I.id).where(I.retur_supplier_id==rec.id))).all()
    nilai={i:dict(jumlah=D(n),bobot_kg=D(kg)) for i,n,kg in rows}
    if len(nilai)!=len(items):raise ValueError('Rincian keluar awal tidak lengkap; perlu penelusuran sumber.')
    receipt=await kembali.baca(db,rec,items,nilai)
    return rec,items,ledger,state,nilai,receipt


def versi(state):return state.versi if state else 0
def catatan(rec,state):return state.keterangan if state and state.keterangan is not None else rec.catatan or ''


async def data(db,identitas,user):
    rec,items,ledger,state,nilai,receipt=await konteks(db,identitas,user)
    # Pembacaan ini tidak membuat draf, memverifikasi, atau menulis stok.
    error=None
    try:
        _,opsi=await s.siapkan(db,rec.penerimaan_tiket_id,user)
    except ValueError as exc:opsi=[];error=str(exc)
    t=await s.tiket(db,rec.timbangan_transaksi_id) if rec.timbangan_transaksi_id else None
    changes=(await db.scalars(select(P).where(P.retur_supplier_id==rec.id).order_by(P.versi))).all()
    return dict(rec=rec,items=items,ledger=ledger,state=state,efektif=nilai,penerimaan_kembali=receipt,
        awal_keluar={x['item_id']:x for x in ledger.snapshot.get('items',[])},
        opsi={x['kunci']:x for x in opsi},error_sumber=error,tiket=t,perubahan=changes,
        versi=versi(state),keterangan=catatan(rec,state))


def _input(jenis,alasan,konfirmasi,kunci):
    if jenis not in ('jumlah','keterangan','batal'):raise ValueError('Jenis tindakan tidak dikenal.')
    if not isinstance(alasan,str) or not alasan.strip() or len(alasan)>2000:raise ValueError('Alasan tindakan wajib diisi, maksimal 2.000 karakter; spasi tidak cukup.')
    if konfirmasi is not True:raise ValueError('Konfirmasi pemeriksaan kesalahan pencatatan atau keberadaan barang wajib dipilih.')
    if not isinstance(kunci,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,64}',kunci):raise ValueError('Identitas permintaan tidak sah; buka ulang formulir.')


async def _tara(db,i,lama,*,kunci=False):
    q=select(KemasanTara).where(KemasanTara.id==lama.kemasan_tara_id)
    kt=await db.scalar(q.with_for_update() if kunci else q)
    if not kt or kt.tara_per_karung_kg is None:raise ValueError('Tara kemasan belum tersedia; koreksi tidak dapat diperiksa.')
    if i.product_sku_id:
        sku=await db.get(ProductSku,i.product_sku_id)
        if not sku or (sku.package_size_id,sku.packaging_material_id)!=(kt.package_size_id,kt.packaging_material_id):
            raise ValueError('Kemasan sumber berubah dari catatan keluar. Periksa relasi terlebih dahulu.')
    tara=s.angka(kt.tara_per_karung_kg,'Tara per karung',1000,'.0001')
    if tara<=0:raise ValueError('Tara kemasan belum sah.')
    return tara


async def _periksa_hilir(db,item,ledger):
    # Sumber yang sudah dikemas ulang atau menjadi isi silo sesudah keluar
    # memerlukan penelusuran transaksi terkait, bukan koreksi sumber lama.
    if item.finished_goods_stock_id:
        from app.models.kemas_ulang import KemasUlang
        ada=await db.scalar(select(KemasUlang.id).where(KemasUlang.sumber_id==item.finished_goods_stock_id,KemasUlang.waktu>=ledger.waktu).limit(1))
    elif item.pk_purchase_batch_id:
        from app.models import PkGudang2Intake,PkTumpukanToSilo
        ada=await db.scalar(select(PkTumpukanToSilo.id).join(PkGudang2Intake,PkGudang2Intake.id==PkTumpukanToSilo.pk_gudang2_intake_id).where(
            PkGudang2Intake.pk_purchase_batch_id==item.pk_purchase_batch_id,PkTumpukanToSilo.waktu>=ledger.waktu,PkTumpukanToSilo.dibatalkan_pada.is_(None)).limit(1))
    else:ada=None
    if ada:raise ValueError('Sumber memiliki transaksi lanjutan setelah barang keluar. Periksa relasi dan audit transaksi tersebut sebelum koreksi jumlah.')


async def _rencana(db,*,identitas,user,jenis,jumlah=None,keterangan='',keberadaan='',alasan,konfirmasi,kunci):
    _input(jenis,alasan,konfirmasi,kunci)
    if not isinstance(keterangan,str):raise ValueError('Keterangan harus berupa teks.')
    rec,items,ledger,state,nilai,receipt=await konteks(db,identitas,user,kunci=True)
    if state and state.dibatalkan:raise ValueError('Pembatalan administratif sudah dicatat. Jangan mengulang atau mengoreksi stok melalui tindakan yang sudah ditutup.')
    snap=dict(retur_supplier_id=rec.id,keluar_peristiwa_id=ledger.peristiwa_id,kode_keluar=ledger.kode,
        jenis=jenis,versi_sebelum=versi(state),alasan=alasan.strip(),keterangan_lama=catatan(rec,state),
        keterangan_baru=keterangan.strip(),keberadaan=keberadaan,items=[],penerimaan=receipt)
    if ledger.snapshot.get('penerimaan_tiket_id')!=rec.penerimaan_tiket_id or ledger.snapshot.get('supplier_id')!=rec.supplier_id or ledger.snapshot.get('tiket_id')!=rec.timbangan_transaksi_id:
        raise ValueError('Hubungan penerimaan, supplier atau tiket berubah dari catatan keluar asli.')
    snap['efektif_sebelum']=[dict(item_id=i.id,**nilai[i.id],warehouse_id=i.warehouse_id,kunci=i.kunci_sumber) for i in items]
    if jenis!='jumlah':
        current=await s.tiket(db,rec.timbangan_transaksi_id,kunci=True)
        if not current:raise ValueError('Tiket terkait belum dapat dibaca. Periksa data terbaru sebelum tindakan.')
        snap['tiket_terkini']=dict(kode=current['kode'],revisi=current.get('jumlah_revisi'),versi=f.versi_tiket(current))
        try:
            _,sources=await s.siapkan(db,rec.penerimaan_tiket_id,user,kunci=True)
            sources={x['kunci']:x for x in sources};snap['error_sumber']=None
        except ValueError as exc:sources={};snap['error_sumber']=str(exc)
        for v,i in zip(snap['efektif_sebelum'],items):
            source=sources.get(i.kunci_sumber,{})
            v.update(nama=i.snapshot['nama'],kode=i.snapshot['kode'],satuan=i.satuan,pemilik=i.snapshot['pemilik'],gudang=i.snapshot['gudang'],lokasi=i.snapshot['lokasi'],stok_kg=source.get('stok_kg'),alokasi_lain_kg=source.get('terikat_kg'))
    if jenis=='keterangan':
        if not isinstance(keterangan,str) or not keterangan.strip() or len(keterangan)>4000:raise ValueError('Keterangan yang benar wajib diisi, maksimal 4.000 karakter.')
        if keterangan.strip()==catatan(rec,state):raise ValueError('Belum ada perubahan keterangan.')
    elif jenis=='batal':
        if keberadaan not in ('di_luar','kembali'):raise ValueError('Pilih keberadaan barang secara eksplisit.')
        if receipt['tersedia'] and any(receipt['jumlah'].values()) and keberadaan=='di_luar':raise ValueError('Sudah ada penerimaan sah. Periksa keberadaan barang dan dokumen terkait.')
        snap['status_fisik']=('barang_masih_di_luar' if keberadaan=='di_luar' else 'seluruh_diterima' if receipt['tersedia'] and receipt['lengkap'] else 'sebagian_belum_kembali' if receipt['tersedia'] and any(receipt['jumlah'].values()) else 'menunggu_penerimaan')
    else:
        if receipt['tersedia'] and any(receipt['jumlah'].values()):raise ValueError('Koreksi jumlah ditahan karena ada penerimaan kembali terkait. Periksa relasi dan audit penerimaan terlebih dahulu.')
        if not isinstance(jumlah,list) or len(jumlah)!=len(items):raise ValueError('Rincian harus mencakup seluruh item pengiriman asal.')
        byid={x.get('item_id'):x for x in jumlah if isinstance(x,dict)}
        if set(byid)!={i.id for i in items} or len(byid)!=len(jumlah):raise ValueError('Item koreksi bukan bagian dari retur yang dituju atau berulang.')
        asal,opsi=await s.siapkan(db,rec.penerimaan_tiket_id,user,kunci=True)
        if asal['supplier_id']!=rec.supplier_id:raise ValueError('Supplier penerimaan asal berubah. Periksa relasi sebelum koreksi.')
        opts={x['kunci']:x for x in opsi};original={a.item_id:a for a in (await db.scalars(select(A).where(A.item_id.in_(byid)))).all()}
        t=await s.tiket(db,rec.timbangan_transaksi_id,kunci=True);s.syarat_tiket(t,rec)
        if t['status_tiket']!='SELESAI':raise ValueError('Tiket harus selesai timbang kedua sebelum pemeriksaan koreksi.')
        final=s.angka(t['berat_barang_kg'],'Hasil akhir tiket',1_000_000,'.001')
        pools={};batas={};tambahan={};batas_tambahan={}
        for i in items:
            x=opts.get(i.kunci_sumber);old=nilai[i.id]
            if not x or (x['satuan'],x['warehouse_id'],x.get('product_sku_id'),x.get('rice_quality_standard_id'),x.get('jenis_produk'))!=(i.satuan,i.warehouse_id,i.product_sku_id,i.rice_quality_standard_id,i.jenis_produk):raise ValueError('Sumber, satuan, pemilik, gudang atau identitas barang berubah dari pengajuan asal.')
            if x['alasan_tidak_bisa'] and not x['alasan_tidak_bisa'].startswith('Stok sumber sudah habis'):raise ValueError(x['alasan_tidak_bisa'])
            if x['stok_kg'] is None:raise ValueError('Saldo sumber terkini belum dapat dipastikan.')
            raw=byid[i.id].get('jumlah')
            if raw is None or isinstance(raw,bool) or not str(raw).strip():raise ValueError('Isi jumlah yang benar untuk setiap item. Gunakan angka 0 secara eksplisit bila barang tidak keluar.')
            n=s.angka(raw,'Jumlah yang benar',1_000_000,'1' if i.satuan=='karung' else '.01')
            if n!=old['jumlah']:await _periksa_hilir(db,i,ledger)
            if n==old['jumlah']:kg=old['bobot_kg']
            elif i.satuan=='kg':kg=n
            elif i.pk_purchase_batch_id:
                from app.penggilingan.gudang2.karung import bobot_per_karung
                kg=bobot_per_karung(x['_row'],jumlah=n).quantize(D('.00000001'),rounding=ROUND_HALF_UP)
            else:
                from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
                row=x['_row']
                # Pakai mesin partai lama dengan keluar milik transaksi ini
                # dikeluarkan dari pembagi; tidak menyunting objek sumber.
                proxy=SimpleNamespace(jumlah_karung=row.jumlah_karung,berat_total_kg=row.berat_total_kg,
                    retur_supplier_keluar_kg=D(row.retur_supplier_keluar_kg)-old['bobot_kg'],
                    retur_supplier_keluar_karung=D(row.retur_supplier_keluar_karung)-old['jumlah'])
                kg=berat_karung_nyata(proxy,n)
            if kg<0 or (n>0 and kg<=0):raise ValueError('Bobot partai belum sah.')
            delta=kg-old['bobot_kg'];mutasi=-delta;saldo=D(x['stok_kg']);alokasi=D(x['terikat_kg'])
            if delta>max(D(0),saldo-alokasi)+ (D('.000001') if i.pk_purchase_batch_id else D(0)):raise ValueError('Tambahan keluar melampaui stok bebas sumber; alokasi transaksi lain harus tetap aman.')
            if i.satuan=='karung':
                from app.services.retur_supplier_reservasi import karung_terikat
                bebas_n=max(D(0),D(x['stok_jumlah'] or 0)-D(await karung_terikat(db,i.kunci_sumber)))
                if n-old['jumlah']>bebas_n:raise ValueError('Karung bebas sumber tidak cukup untuk tambahan koreksi.')
            if x['_batas_pool'] is not None:
                key=x['_pool'];pools[key]=pools.get(key,D(0))+delta;batas[key]=D(x['_batas_pool'])
            if x['_tambahan_pool']:
                key,bound=x['_tambahan_pool'];tambahan[key]=tambahan.get(key,D(0))+delta;batas_tambahan[key]=D(bound)
            tara=await _tara(db,i,original[i.id],kunci=True) if i.satuan=='karung' and n>0 else D(0)
            snap['items'].append(dict(item_id=i.id,kunci=i.kunci_sumber,nama=x['nama'],kode=x['kode'],pemilik=x['pemilik'],gudang=x['gudang'],lokasi=x['lokasi'],satuan=i.satuan,
                jumlah_lama=old['jumlah'],bobot_lama=old['bobot_kg'],jumlah_baru=n,bobot_baru=kg,mutasi_kg=mutasi,mutasi_jumlah=old['jumlah']-n,
                stok_sebelum_kg=saldo,stok_sesudah_kg=saldo+mutasi,alokasi_lain_kg=alokasi,tersedia_sesudah_kg=saldo+mutasi-alokasi,
                karung_sebelum=x['stok_jumlah'] if i.satuan=='karung' else None,karung_sesudah=D(x['stok_jumlah'] or 0)+old['jumlah']-n if i.satuan=='karung' else None,tara_per_karung_kg=tara))
        if not any(x['jumlah_baru']!=x['jumlah_lama'] for x in snap['items']):raise ValueError('Belum ada perubahan jumlah.')
        if any(pools[k]>batas[k]+D('.000001') for k in pools) or any(tambahan[k]>batas_tambahan[k]+D('.000001') for k in tambahan):raise ValueError('Pemakaian gabungan koreksi melampaui saldo bebas dan alokasi transaksi lain.')
        lines=[BarisBobot(x['bobot_baru'],int(x['jumlah_baru']) if x['satuan']=='karung' else 0,x['tara_per_karung_kg']) for x in snap['items'] if x['bobot_baru']>0]
        check=periksa_bobot(lines,tiket_selesai=True,berat_tiket_kg=final,pernah_selisih_besar=bool(state and state.wajib_manual))
        snap.update(total_lama=sum((x['bobot_lama'] for x in snap['items']),D(0)),total_baru=check.berat_rincian_kg,
            hasil_kg=final,selisih_kg=check.selisih_kg,toleransi_kg=check.toleransi_kg,status_hitung=check.status,
            tiket_id=t['id'],kode_tiket=t['kode'],revisi_tiket=t.get('jumlah_revisi',0),versi_tiket=f.versi_tiket(t),bobot_tiket=f.bobot_tiket(t))
    snap=f.bersih(snap);snap['dasar']=s.sidik(snap)
    return rec,state,snap


async def _audit(db,rec,user,aksi,old,new,alasan):
    await log_activity(db,table_name='retur_supplier',record_id=rec.id,action='UPDATE',changed_by=user.id,aksi=aksi,
        old_value=json.dumps(f.bersih(old)),new_value=json.dumps(f.bersih(new)),alasan=alasan)


async def _proof(db,state,snap):
    base=state.dasar_besar if state else None
    if not base:return False
    amounts=[(x['item_id'],x['jumlah_baru'],x['bobot_baru']) for x in snap['items']]
    if f.bersih(amounts)!=base['jumlah']:
        # Setiap inspeksi disimpan beserta alasan dan konfirmasi pemeriksaan
        # fisik oleh server; bukan metadata/revisi yang dinaikkan klien.
        return True
    if snap['bobot_tiket']==base['bobot_tiket'] or int(snap['revisi_tiket'] or 0)<=int(base['revisi_tiket'] or 0):return False
    if not await db.scalar(text("SELECT to_regclass('timbangan_audit')")):return False
    logs=(await db.execute(text("SELECT nilai_sebelum,nilai_sesudah FROM timbangan_audit WHERE entitas='transaksi' AND entitas_id=:kode AND aksi='KOREKSI' AND waktu>:waktu"),dict(kode=snap['kode_tiket'],waktu=datetime.fromisoformat(base['waktu'])))).all()
    for a,b in logs:
        try:
            a=json.loads(a or '{}');b=json.loads(b or '{}')
            if any(k in a and k in b and D(str(a[k]))!=D(str(b[k])) and D(str(b[k]))==D(snap['bobot_tiket'][k]) for k in ('timbang1_kg','timbang2_kg','berat_barang_kg')):return True
        except (ValueError,TypeError,InvalidOperation):continue
    return False


async def periksa(db,*,user,**payload):
    async with db.begin_nested():
        await s.pelaku(db,user,tulis=True)
        used=await db.scalar(select(P.peristiwa_id).join(buku.Peristiwa,buku.Peristiwa.id==P.peristiwa_id).where(buku.Peristiwa.kunci_kiriman=='retur_supplier_perubahan:'+payload['kunci']))
        if used:raise ValueError('Permintaan sudah tercatat. Periksa status atau riwayat sebelum mengulang.')
        rec,state,snap=await _rencana(db,user=user,**payload)
        if state is None:
            state=E(retur_supplier_id=rec.id,versi=0,dibatalkan=False,wajib_manual=False);db.add(state);await db.flush()
        old=await db.get(F,payload['kunci'])
        if old and (old.retur_supplier_id!=rec.id or old.input_by!=user.id):raise PermissionError('Draf tindakan bukan milik pengajuan atau pelaku ini.')
        status='siap' if snap['jenis']!='jumlah' else 'terverifikasi_otomatis'
        if snap['jenis']=='jumlah':
            if snap['status_hitung']=='perlu_koreksi':
                state.wajib_manual=True;state.dasar_besar=f.bersih(dict(jumlah=[(x['item_id'],x['jumlah_baru'],x['bobot_baru']) for x in snap['items']],bobot_tiket=snap['bobot_tiket'],revisi_tiket=snap['revisi_tiket'],waktu=now_local().isoformat()))
                status='perlu_koreksi'
            elif snap['status_hitung']=='tertahan':status='tertahan'
            elif state.wajib_manual:status='siap_manual' if await _proof(db,state,snap) else 'perlu_koreksi'
        snap.update(status=status,waktu=now_local().isoformat(),oleh=user.id)
        if old:await _audit(db,rec,user,'retur_supplier_koreksi_periksa',old.snapshot,snap,payload['alasan'])
        else:await _audit(db,rec,user,'retur_supplier_koreksi_periksa',None,snap,payload['alasan'])
        draft=old or F(kunci=payload['kunci'],retur_supplier_id=rec.id,input_by=user.id)
        draft.versi=versi(state);draft.snapshot=snap;draft.status=status;draft.waktu=now_local();db.add(draft)
        await db.flush();return snap


async def manual(db,*,user,identitas,kunci,dasar,catatan,konfirmasi):
    if not isinstance(catatan,str) or not catatan.strip() or len(catatan)>2000 or konfirmasi is not True:raise ValueError('Catatan dan konfirmasi pemeriksaan manual wajib diisi.')
    async with db.begin_nested():
        await konteks(db,identitas,user,kunci=True)
        d=await db.get(F,kunci)
        if not d or d.retur_supplier_id!=identitas or d.status!='siap_manual' or d.snapshot['dasar']!=dasar:raise ValueError('Periksa ulang koreksi sah sebelum verifikasi manual.')
        rec,state,new=await _rencana(db,user=user,**payload_draf(d))
        if new['dasar']!=dasar or not await _proof(db,state,new):raise ValueError('Saldo, versi atau tiket berubah; periksa ulang tanpa menghapus isian.')
        if abs(D(new['selisih_kg']))>D(new['toleransi_kg']):raise ValueError('Selisih koreksi masih di luar toleransi.')
        d.status='terverifikasi_manual';d.snapshot=dict(d.snapshot,status=d.status,pemeriksa=user.id,catatan_manual=catatan.strip(),waktu_manual=now_local().isoformat())
        await _audit(db,rec,user,'retur_supplier_koreksi_manual',None,d.snapshot,catatan.strip());await db.flush();return d.snapshot


def payload_draf(d):
    x=d.snapshot
    return dict(identitas=d.retur_supplier_id,kunci=d.kunci,jenis=x['jenis'],jumlah=[dict(item_id=i['item_id'],jumlah=i['jumlah_baru']) for i in x['items']],
        keterangan=x['keterangan_baru'],keberadaan=x['keberadaan'],alasan=x['alasan'],konfirmasi=True)


async def simpan(db,*,user,identitas,kunci,dasar,konfirmasi):
    if konfirmasi is not True:raise ValueError('Konfirmasi akhir dampak wajib dipilih.')
    async with db.begin_nested():
        await s.pelaku(db,user,tulis=True);await s.keluar._kunci_saldo_keluar(db)
        existing=await db.scalar(select(P).join(buku.Peristiwa,buku.Peristiwa.id==P.peristiwa_id).where(buku.Peristiwa.kunci_kiriman=='retur_supplier_perubahan:'+kunci))
        if existing:
            await s.ambil(db,identitas,user)
            if existing.retur_supplier_id!=identitas or existing.snapshot['dasar']!=dasar:raise ValueError('Permintaan sudah dicatat untuk data lain.')
            return existing
        d=await db.get(F,kunci)
        if not d or d.retur_supplier_id!=identitas or d.input_by!=user.id or d.snapshot['dasar']!=dasar:raise ValueError('Draf atau pemeriksaan tindakan tidak sesuai.')
        rec,state,snap=await _rencana(db,user=user,**payload_draf(d))
        if snap['dasar']!=dasar or versi(state)!=d.versi:raise ValueError('Saldo, versi, hubungan sumber atau revisi tiket berubah. Isian tetap tersedia; periksa dampak ulang sebelum konfirmasi.')
        if snap['jenis']=='jumlah':
            if d.status not in ('terverifikasi_otomatis','terverifikasi_manual') or abs(D(snap['selisih_kg']))>D(snap['toleransi_kg']):raise ValueError('Pemeriksaan koreksi yang sah diperlukan.')
            if state and state.wajib_manual and (d.status!='terverifikasi_manual' or not await _proof(db,state,snap)):raise ValueError('Koreksi sah dan verifikasi manual masih diperlukan.')
        snap.update(versi_sesudah=d.versi+1,verifikasi=dict(status=d.status,pemeriksa=d.snapshot.get('pemeriksa'),catatan=d.snapshot.get('catatan_manual'),waktu=d.snapshot.get('waktu_manual')),kunci=kunci)
        e=await buku.catat(db,jenis='retur_supplier_batal_administratif' if snap['jenis']=='batal' else 'retur_supplier_koreksi',pelaku_id=user.id,kunci_kiriman='retur_supplier_perubahan:'+kunci,muatan=snap)
        await _audit(db,rec,user,'retur_supplier_selesai_'+snap['jenis'],dict(versi=d.versi),snap,snap['alasan'])
        await db.flush();return await db.get(P,e.id)
