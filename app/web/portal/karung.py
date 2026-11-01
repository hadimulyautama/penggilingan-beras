"""Pisahkan kemasan kosong milik kontak dari karung yang berisi barang."""


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
            masuk_kg=dari_batch(batch).kg,ukuran=batch.ukuran_karung_kg)
