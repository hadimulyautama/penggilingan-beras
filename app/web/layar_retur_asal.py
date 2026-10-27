"""Retur dimulai dari item yang benar-benar dikirim, bukan katalog bebas."""
from decimal import Decimal

from app.web.portal.scope import is_customer_read
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import OutgoingRecord, User, PackagingMaterial, Pelanggan
from app.penggilingan.inventory.models import ReturPemeriksaanLog, ReturRincian
from app.services import retur_pengajuan as layanan
from app.services.retur_penerimaan import periksa_dan_terima, _koreksi_terbukti
from app.web.layar_retur import _boleh
from app.web.security import butuh_akun
from app.web.tampilan import redirect, render_laci

router = APIRouter(tags=['webapp'])


def wajib(akun):
    if not _boleh(akun):
        raise HTTPException(403, 'Penerimaan retur hanya tersedia untuk Admin.')


@router.get('/retur/tiket/{tiket_id}')
async def tiket_retur(tiket_id: int, request: Request, akun=Depends(butuh_akun)):
    if not is_customer_read(request):
        wajib(akun)
    async with SessionLocal() as db:
        tiket = (await db.execute(text('''
            SELECT t.id,t.kode,t.status_tiket,t.status_transaksi,t.nomor_polisi,
                   t.nama_sopir,t.timbang1_kg,t.timbang2_kg,t.berat_barang_kg,
                   t.timbang1_waktu,t.timbang2_waktu,p.nama_pelanggan
            FROM timbangan_transaksi t LEFT JOIN pelanggan p ON p.id=t.pelanggan_id
            WHERE t.id=:id AND t.arah='RETUR_MASUK' AND
              (EXISTS(SELECT 1 FROM retur_rincian r WHERE r.timbangan_transaksi_id=t.id)
               OR EXISTS(SELECT 1 FROM customer_returns c WHERE c.timbangan_transaksi_id=t.id))
        '''), {'id': tiket_id})).mappings().first()
    if not tiket:
        raise HTTPException(404, 'Tiket retur tidak tersedia.')
    return await render_laci(request, 'retur_tiket.html', layar='barang_keluar', tiket=tiket)


@router.get('/barang-keluar/{pengiriman_id}/retur')
@router.get('/retur/pengajuan/{pengajuan_id}')
async def formulir(request: Request, pengiriman_id: int | None = None,
                   pengajuan_id: int | None = None, akun=Depends(butuh_akun)):
    if not is_customer_read(request):
        wajib(akun)
    from app.web.layar_keluar import _nama_barang
    from app.services.jasa import nama_pemilik_banyak
    async with SessionLocal() as db:
        rincian = await db.get(ReturRincian, pengajuan_id) if pengajuan_id else None
        if pengajuan_id and (not rincian or not rincian.outgoing_record_id):
            raise HTTPException(404, 'Pengajuan retur tidak ditemukan.')
        oid = rincian.outgoing_record_id if rincian else pengiriman_id
        asal = await db.get(OutgoingRecord, oid)
        if not asal or asal.status != 'selesai':
            raise HTTPException(404, 'Pengiriman asal tidak tersedia untuk retur.')
        pelanggan_asal = asal.nama_pembeli or await db.scalar(select(Pelanggan.nama_pelanggan).where(Pelanggan.id == asal.pelanggan_id))
        items, terpakai = await layanan.sisa_asal(db, asal.id, kecuali=pengajuan_id)
        nama = await _nama_barang(db, [(asal, items)])
        pemilik = await nama_pemilik_banyak(db, {i.jasa_id for i in items if i.jasa_id})
        muatan = {m['outgoing_item_id']: m for m in rincian.muatan} if rincian else {}
        baris = []
        kemasan_gabah = (await db.scalars(select(PackagingMaterial).where(
            PackagingMaterial.aktif.is_(True)).order_by(PackagingMaterial.nama))).all()
        isian=getattr(request.state,'retur_isian',None)
        for i in items:
            if i.berat_kg<=0:
                continue
            karung = i.item_type == 'finished_goods'
            dikirim = i.jumlah_karung or 0 if karung else Decimal(str(i.berat_kg))
            lama = terpakai[i.id]['karung' if karung else 'kg']
            diterima = terpakai[i.id]['diterima_karung' if karung else 'diterima_kg']
            m = muatan.get(i.id)
            baris.append(dict(id=i.id, nama=nama.get(i.id, i.item_type),
                pemilik=pemilik.get(i.jasa_id, 'Milik pabrik'), satuan='karung' if karung else 'kg',
                dikirim=dikirim, sebelumnya=diterima, tertunda=lama-diterima, sisa=max(dikirim-lama, 0),
                catatan=m.get('catatan_item', '') if m else '',
                pilih_kemasan=i.item_type == 'gabah_langsung',
                hitung_karung=i.item_type in ('pk_langsung','pk_g2','gabah_langsung'),
                karung_dikirim=i.jumlah_karung,
                sisa_karung=max(i.jumlah_karung-terpakai[i.id]['karung'],0) if i.jumlah_karung is not None else 100_000,
                jumlah_karung=m['jumlah_karung'] if m else 0,
                kemasan_id=m.get('packaging_material_id') if m else None,
                jumlah=(m['jumlah_karung'] if karung else m['berat_kg']) if m else 0))
        if isian is not None:
            nilai=dict(zip(isian.getlist('item_id'),isian.getlist('jumlah')))
            for b in baris:
                b.update(jumlah=nilai.get(str(b['id']),b['jumlah']),catatan=isian.get(f"catatan_item_{b['id']}",b['catatan']),jumlah_karung=isian.get(f"karung_{b['id']}",b['jumlah_karung']),kemasan_id=isian.get(f"kemasan_{b['id']}",b['kemasan_id']))
        tickets = (await db.execute(text('''
            SELECT t.id,t.kode,t.nomor_polisi,t.status_tiket,t.berat_barang_kg
            FROM timbangan_transaksi t
            WHERE t.arah='RETUR_MASUK' AND t.status_transaksi='AKTIF'
              AND t.status_tiket IN ('TERBUKA','SELESAI') AND t.pelanggan_id=:pid
              AND NOT EXISTS (SELECT 1 FROM customer_returns c WHERE c.timbangan_transaksi_id=t.id)
              AND NOT EXISTS (SELECT 1 FROM retur_rincian r WHERE r.timbangan_transaksi_id=t.id
                AND r.outgoing_record_id IS NOT NULL AND r.id IS DISTINCT FROM :rid)
            ORDER BY t.id DESC
        '''), {'pid': asal.pelanggan_id, 'rid': pengajuan_id})).mappings().all()
        logs = (await db.scalars(select(ReturPemeriksaanLog).where(
            ReturPemeriksaanLog.retur_rincian_id == pengajuan_id).order_by(
            ReturPemeriksaanLog.id.desc()))).all() if pengajuan_id else []
        aktor_ids = {l.pelaku_id for l in logs if l.pelaku_id}
        aktor = dict((await db.execute(select(User.id, User.nama).where(User.id.in_(aktor_ids)))).all()) if aktor_ids else {}
        # Pembacaan tambahan hanya untuk tab; tidak menjalankan pemeriksaan/penerimaan.
        pengaju = await db.get(User, rincian.input_by) if rincian else None
        tiket_id_detail = rincian.timbangan_transaksi_id if rincian else request.query_params.get('tiket')
        try:
            tiket_id_detail = int(tiket_id_detail) if tiket_id_detail else None
        except (TypeError, ValueError):
            tiket_id_detail = None
        tiket_detail = (await db.execute(text('''
            SELECT t.kode,t.status_tiket,t.status_transaksi,t.nomor_polisi,t.nama_sopir,
                   t.timbang1_kg,t.timbang2_kg,t.timbang1_waktu,t.timbang2_waktu,
                   t.netto_timbangan_kg,t.berat_barang_kg,p.nama_pelanggan
            FROM timbangan_transaksi t LEFT JOIN pelanggan p ON p.id=t.pelanggan_id
            WHERE t.id=:id AND t.arah='RETUR_MASUK'
              AND (t.pelanggan_id=:pid OR :tertaut)
        '''), {'id':tiket_id_detail,'pid':asal.pelanggan_id,'tertaut':bool(rincian)})).mappings().first()
        manual_siap = bool(rincian and rincian.status_pemeriksaan == 'calon_manual'
                           and await _koreksi_terbukti(db, rincian))
    return await render_laci(request, 'retur_asal.html', layar='barang_keluar',
        asal=asal, rincian=rincian, baris=baris, tiket_detail=tiket_detail,
        pengaju=pengaju.nama if pengaju else None, tickets=tickets, logs=logs, aktor=aktor,
        nama_item=nama, kemasan_gabah=kemasan_gabah, manual_siap=manual_siap,
        pelanggan_asal=pelanggan_asal,
        gagal=getattr(request.state,'retur_gagal',None) or request.query_params.get('gagal'), pesan=request.query_params.get('pesan'),
        isian=isian,
        tiket_terpilih=isian.get('tiket_id') if isian is not None else rincian.timbangan_transaksi_id if rincian else request.query_params.get('tiket'),
        terkunci=bool(rincian and (rincian.customer_return_id or rincian.status_pemeriksaan == 'dibatalkan')))


@router.post('/barang-keluar/{pengiriman_id}/retur')
async def simpan(request: Request, pengiriman_id: int, akun=Depends(butuh_akun)):
    wajib(akun)
    form = await request.form()
    pengajuan_id = None
    try:
        pengajuan_id = int(form['pengajuan_id']) if form.get('pengajuan_id') else None
        ids, nilai = form.getlist('item_id'), form.getlist('jumlah')
        if len(ids) != len(nilai) or len(set(ids)) != len(ids):
            raise ValueError('Rincian item tidak lengkap atau berulang.')
        jumlah = {int(i): n for i, n in zip(ids, nilai)}
        if len(jumlah) != len(ids):
            raise ValueError('Identitas item berulang.')
        async with SessionLocal() as db:
            rincian = await layanan.simpan(db, pengiriman_id=pengiriman_id,
                tiket_id=int(form.get('tiket_id', '')), jumlah=jumlah,
                pelaku_id=akun.user.id, pengajuan_id=pengajuan_id,
                alasan=form.get('alasan'), catatan=form.get('catatan'),
                kemasan_item={int(i): form.get(f'kemasan_{i}') for i in ids},
                karung_item={int(i): form.get(f'karung_{i}') for i in ids},
                catatan_item={int(i): str(form.get(f'catatan_item_{i}', '')) for i in ids})
            await periksa_dan_terima(db, rincian.id)
            await db.commit()
            pengajuan_id = rincian.id
    except (ValueError, KeyError) as exc:
        if request.headers.get('accept')=='application/json':
            return JSONResponse({'detail':str(exc)},status_code=400)
        # Pembaca ulang dengan masukan yang sama. Validasi tidak boleh
        # mengalihkan ke GET yang membuang jumlah, catatan, dan alasan koreksi.
        request.state.retur_isian=form;request.state.retur_gagal=str(exc)
        return await formulir(request,pengiriman_id=pengiriman_id,pengajuan_id=pengajuan_id,akun=akun)
    alamat=f'/retur/pengajuan/{pengajuan_id}?pesan=Pengajuan%20retur%20tersimpan.'
    if request.headers.get('accept')=='application/json':
        return JSONResponse({'ok':True,'alamat':alamat,'pengajuan_id':pengajuan_id})
    return redirect(alamat)


@router.post('/retur/pengajuan/{pengajuan_id}/verifikasi')
async def verifikasi(pengajuan_id: int, request: Request, akun=Depends(butuh_akun)):
    wajib(akun)
    try:
        async with SessionLocal() as db:
            receipt = await periksa_dan_terima(db, pengajuan_id, manual=True, pelaku=akun.user)
            # Hasil yang masih tertahan harus tersimpan agar layar tidak
            # menampilkan data pemeriksaan lama seolah-olah sudah memenuhi.
            await db.commit()
            if not receipt:
                raise ValueError('Verifikasi belum dapat dilakukan. Koreksi data sampai seluruh pemeriksaan memenuhi syarat.')
    except ValueError as exc:
        if request.headers.get('accept')=='application/json':return JSONResponse({'detail':str(exc)},status_code=400)
        return redirect(f'/retur/pengajuan/{pengajuan_id}?gagal={quote(str(exc), safe="")}')
    if request.headers.get('accept')=='application/json':return JSONResponse({'ok':True,'alamat':f'/retur/{receipt.id}'})
    return redirect(f'/retur/{receipt.id}')


@router.post('/retur/pengajuan/{pengajuan_id}/batalkan')
async def batalkan(pengajuan_id: int, request: Request, akun=Depends(butuh_akun)):
    wajib(akun)
    form = await request.form()
    try:
        async with SessionLocal() as db:
            await layanan.batalkan(db, identitas=pengajuan_id, pelaku=akun.user, alasan=form.get('alasan'))
            await db.commit()
    except ValueError as exc:
        if request.headers.get('accept')=='application/json':return JSONResponse({'detail':str(exc)},status_code=400)
        return redirect(f'/retur/pengajuan/{pengajuan_id}?gagal={quote(str(exc), safe="")}')
    alamat=f'/retur/pengajuan/{pengajuan_id}?pesan=Pengajuan%20dibatalkan.%20Tidak%20ada%20stok%20yang%20ditambahkan.'
    if request.headers.get('accept')=='application/json':return JSONResponse({'ok':True,'alamat':alamat})
    return redirect(alamat)
