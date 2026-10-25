"""Pembaca Mulai penyosohan: saldo/komposisi lama, tanpa klaim atau penggabungan."""
from sqlalchemy import select
from app.models import (Jasa, Silo, PkGudang2Intake, PkTumpukanToSilo,
    PkPurchaseBatch, InternalTransfer, BerasKeSilo, BrokenKeSilo,
    HasilSampingKeSilo, PolishingProcess, PolishingSiloUsage)
from app.penggilingan.gudang2.service import get_g2_silo, hitung_stok_silo, komposisi_bahan_silo
from app.penggilingan.gudang1.services.bobot import Bobot, PASTI, PERKIRAAN, TAK_DIKETAHUI, jumlah, dari_batch
from app.services.jasa import pemilik_silo_g2, cocok_pemilik
from app.web.form_tambah_silo_giling import pemilik

LABEL = dict(pk="PK", beras_putih="Beras olah ulang", broken="Broken",
             menir="Menir", reject="Reject", belum_dikenal="Jenis belum teridentifikasi")

async def baca_silo(db, silo):
    kg = await hitung_stok_silo(db, silo.id)
    komposisi = await komposisi_bahan_silo(db, silo.id, target_kg=kg)
    komposisi = {j:v for j,v in komposisi.items() if v > 0.01}
    ids = list(await pemilik_silo_g2(db, silo.id))
    nama = list(dict.fromkeys([await pemilik(db, j) for j in ids]))
    orders = list((await db.scalars(select(Jasa.kode).where(Jasa.id.in_([j for j in ids if j])).order_by(Jasa.id))).all())
    jalan = (await db.execute(select(PolishingProcess).join(PolishingSiloUsage,
        PolishingSiloUsage.polishing_process_id == PolishingProcess.id).where(
        PolishingSiloUsage.silo_id == silo.id, PolishingProcess.status == "proses",
        PolishingSiloUsage.berat_akhir_kg.is_(None)))).scalars().first()
    # Riwayat asal bukan alokasi sisa per lot. Bobotnya tidak pernah dijumlah
    # kembali ke saldo; konsumsi/FIFO tetap milik helper komposisi di atas.
    sumber, belum, sementara = [], 0, False
    async def asal(r, jenis, kode, jid, b=None, dinamis=False):
        nonlocal belum, sementara
        berat = r.berat_kg
        status = dari_batch(b) if dinamis else Bobot(float(berat) if berat is not None else None, PASTI if berat is not None else TAK_DIKETAHUI)
        if dinamis:
            belum += berat is None
            sementara = sementara or not status.pasti
        sumber.append(dict(kode=kode, jenis=LABEL.get(jenis, LABEL['belum_dikenal']),
            bobot=Bobot(float(berat) if berat is not None else None, status.keadaan, 1 if berat is None else 0).teks(),
            pemilik=await pemilik(db, jid), waktu=r.waktu_masuk.isoformat() if hasattr(r, 'waktu_masuk') else r.waktu.isoformat()))
    for r in (await db.scalars(select(PkGudang2Intake).where(PkGudang2Intake.silo_id == silo.id).order_by(PkGudang2Intake.id))).all():
        b = await db.get(PkPurchaseBatch, r.pk_purchase_batch_id) if r.pk_purchase_batch_id else None
        t = await db.get(InternalTransfer, r.internal_transfer_id) if r.internal_transfer_id else None
        await asal(r, 'pk', b.kode_batch if b else t.kode_transfer if t else "Asal belum tertaut", r.jasa_id)
    for r, intake in (await db.execute(select(PkTumpukanToSilo, PkGudang2Intake).join(PkGudang2Intake,
        PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id).where(PkTumpukanToSilo.silo_id == silo.id).order_by(PkTumpukanToSilo.id))).all():
        b = r.batch
        await asal(r, 'pk', r.kode_pindah + (" · " + b.kode_batch if b else ""), intake.jasa_id,
            b, r.jumlah_karung is not None and r.pemakaian_silo_id is None)
    for model, jenis in [(BerasKeSilo, 'beras_putih'), (BrokenKeSilo, 'broken'), (HasilSampingKeSilo, None)]:
        for r in (await db.scalars(select(model).where(model.silo_id == silo.id).order_by(model.id))).all():
            await asal(r, jenis or r.jenis, r.kode_pindah, r.jasa_id)
    keadaan = TAK_DIKETAHUI if belum else PERKIRAAN if sementara else PASTI
    bobot = Bobot(kg if kg or not belum else None, keadaan, belum)
    data = dict(nama=silo.nama_silo, bobot=bobot.teks(), pemilik=" · ".join(nama) or "Pemilik belum tercatat",
        pesanan=orders, jumlah_sumber=len(sumber), asal=[LABEL.get(j, LABEL['belum_dikenal']) for j in komposisi],
        komposisi=[dict(jenis=LABEL.get(j, LABEL['belum_dikenal']), bobot=Bobot(v, keadaan, belum).teks()) for j,v in komposisi.items()],
        sumber=sumber, siap=kg > 0 and jalan is None,
        proses=jalan.kode_proses if jalan else None,
        detail=f"/proses-aktif/sosoh/{jalan.kode_proses}" if jalan else None,
        final=bobot.pasti, belum_dikenal=bool(komposisi.get('belum_dikenal')))
    return data, bobot, ids

async def ringkasan(db, pilihan):
    pilihan = list(dict.fromkeys(str(x).strip().upper() for x in pilihan if str(x or '').strip()))
    silos, bobots, ids, peringatan = [], [], [], []
    for n in pilihan:
        silo = await get_g2_silo(db, n)
        if silo is None:
            silos.append(dict(nama='Silo '+n, bobot='Belum tersedia', siap=False, sumber=[], komposisi=[]))
            peringatan.append('Silo '+n+' tidak ditemukan atau tidak aktif di Gudang 2.')
            continue
        d,b,j = await baca_silo(db, silo)
        silos.append(d);bobots.append(b);ids.extend(j)
        if not d['siap']:
            peringatan.append(d['nama'] + (' sedang dipakai '+d['proses']+'.' if d['proses'] else ' tidak memiliki saldo bahan yang siap.'))
        if not b.pasti:
            peringatan.append(d['nama']+': bahan karung belum final; bobot tetap mengikuti sumber dan koreksi timbang yang berlaku.')
        if d['belum_dikenal']:
            peringatan.append(d['nama']+': jejak jenis bahan belum lengkap; bagian belum teridentifikasi tidak dianggap PK.')
    ids = list(dict.fromkeys(ids))
    cocok = all([await cocok_pemilik(db, ids[0], j) for j in ids[1:]]) if ids else True
    if not cocok:
        peringatan.append('Pemilik berbeda: bahan pabrik dan jasa, atau pelanggan berbeda, tidak dapat digabung. Perbaiki centang silo.')
    elif len(ids) > 1:
        peringatan.append('Pelanggan sama, pesanan berbeda. Pesanan administratif digabung otomatis oleh layanan saat disimpan.')
    total = jumlah(bobots) if bobots else None
    return dict(pilihan=pilihan, silos=silos, bobot=total.teks() if total else 'Belum tersedia',
        final=total.pasti if total else False, jumlah_sumber=sum(d.get('jumlah_sumber',0) for d in silos),
        pemilik=' · '.join(dict.fromkeys(d.get('pemilik','') for d in silos if d.get('pemilik'))) if cocok else 'Kepemilikan belum cocok',
        cocok=cocok, siap=bool(silos) and all(d['siap'] for d in silos) and cocok, peringatan=peringatan)
