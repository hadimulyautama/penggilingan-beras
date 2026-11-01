"""Pisahkan kemasan kosong milik kontak dari karung yang berisi barang."""
import re


def ringkasan_berisi(teks, *, batch=None, sisa_kg=None):
    """Jumlah tercatat atau ekuivalen dari bobot per karung native, bukan nominal."""
    if not teks:return dict(jumlah=None,label=None,perkiraan=False)
    match=re.match(r'(?:sisa )?(-?\d+ karung|kurang dari 1 karung)',teks)
    if not match:return dict(jumlah=None,label=teks,perkiraan=True)
    jumlah=match[1]
    perkiraan=' ~ ' in teks or ' — ' in teks
    if perkiraan and batch is not None and sisa_kg is not None:
        from decimal import Decimal
        from app.penggilingan.gudang2.karung import bobot_per_karung
        bobot=bobot_per_karung(batch)
        if bobot and bobot>0:
            nilai=Decimal(str(sisa_kg))/bobot
            if 0<nilai<1:jumlah='kurang dari 1 karung'
            else:jumlah=f'{nilai:,.2f}'.rstrip('0').rstrip('.').replace(',','_').replace('.',',').replace('_','.')+' karung'
    label=('Setara '+jumlah if jumlah=='kurang dari 1 karung' else 'Setara sekitar '+jumlah) if perkiraan else jumlah+' tercatat'
    return dict(jumlah=jumlah,label=label,perkiraan=perkiraan)


def baris_kosong(rows):
    # Pembaca native mencakup kombinasi pelanggan lain dengan saldo nol.
    # Hanya saldo pelanggan ini yang diproyeksikan ke HTML. Defisit terlihat.
    return [{k:r[k] for k in ('nama','merk','ukuran','gudang','lembar')}
        for r in rows if r['lembar']!=0 and r.get('kode')!='bekas']


async def kosong(db,scope):
    from app.penggilingan.inventory.packaging import stok_kemasan_rinci
    return baris_kosong(await stok_kemasan_rinci(db,pelanggan_id=scope.reader.pelanggan_id))


async def siapkan_detail(request,ctx):
    t=ctx.get('detail_kartu')
    if not t or ctx.get('detail_gudang')!='g2' or not t.jumlah_karung:return
    from app.database import SessionLocal
    from app.models import PkGudang2Intake,PkPurchaseBatch
    from app.penggilingan.gudang1.services.bobot import dari_batch
    scope=request.state.portal_scope
    if t.intake_id not in scope.ids(PkGudang2Intake):return
    async with SessionLocal() as db:
        intake=await db.get(PkGudang2Intake,t.intake_id)
        if intake.pk_purchase_batch_id not in scope.ids(PkPurchaseBatch):return
        batch=await db.get(PkPurchaseBatch,intake.pk_purchase_batch_id)
        ctx['portal_pk_karung']=dict(stok_kg=None if intake.berat_kg is None else t.tersedia,
            masuk_kg=dari_batch(batch).kg,ukuran=batch.ukuran_karung_kg,
            **ringkasan_berisi(t.ringkasan_karung,batch=batch,sisa_kg=None if intake.berat_kg is None else t.tersedia))
