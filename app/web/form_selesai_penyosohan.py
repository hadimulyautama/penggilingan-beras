"""Pembacaan formulir penutupan; tidak mengikat sumber atau menyinkronkan stok.

Token tetap diterbitkan pemeriksaan domain lama. Pembaca ini juga melayani
formulir sebelum seluruh silo diperiksa, sehingga sisa kosong harus tetap
berbeda dari nol dan setiap siklus ditampilkan dengan identitasnya sendiri.
"""
from sqlalchemy import select
from app.models import PolishingProcess, PolishingSiloUsage, Silo, Jasa
from app.penggilingan.gudang2 import polishing as p
from app.penggilingan.gudang2.karung import bobot_pemakaian
from app.penggilingan.gudang1.services.jeda import jeda_terbuka
from app.services.jasa import nama_pemilik
from app.services.proses_aktif import _waktu
from app.services.stok import output_sosoh, nama_produk


async def ringkasan(db, *, kode_proses):
    proc = await db.scalar(select(PolishingProcess).where(
        PolishingProcess.kode_proses == kode_proses))
    if proc is None:
        raise ValueError('Proses penyosohan tidak ditemukan.')
    rows = (await db.execute(select(PolishingSiloUsage, Silo.nama_silo)
        .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
        .where(PolishingSiloUsage.polishing_process_id == proc.id)
        .order_by(PolishingSiloUsage.id))).all()
    usages = [r for r, _ in rows]
    lengkap = bool(rows) and all(r.berat_akhir_kg is not None for r in usages)
    bobot = bobot_pemakaian(usages) if lengkap and all(r.berat_terpakai_kg is not None for r in usages) else None
    hasil = await output_sosoh(db, proc.id)
    # Neraca dan kelompok beras berasal dari helper yang sama dengan laporan;
    # jangan memakai kelompok stok yang sengaja tidak memasukkan beras_b.
    neraca = p.neraca_sosoh(bobot.angka() if bobot else 0, hasil)
    jeda = await jeda_terbuka(db, 'penyosohan', proc.id)
    jasa = await db.get(Jasa, proc.jasa_id) if proc.jasa_id else None
    return dict(kode_proses=proc.kode_proses, id=proc.id,
        pemilik=await nama_pemilik(db, proc.jasa_id) if proc.jasa_id else 'Pabrik',
        kepemilikan='Titipan jasa' if proc.jasa_id else 'Milik pabrik',
        pesanan=jasa.kode if jasa else None,
        status='selesai' if proc.status == 'selesai' else
            ('dijeda' if jeda else 'berjalan') if proc.status == 'proses' else 'belum_diketahui',
        sebab_jeda=jeda.sebab if jeda else None, mulai=_waktu(proc.waktu_mulai),
        sumber=[dict(id=r.id, silo=nama, awal=None if r.bobot_karung_dinamis and any(m.berat_kg is None for m in r.pemindahan_karung if not m.selama_proses and m.dibatalkan_pada is None) else float(r.berat_awal_kg),
            tambahan=None if r.bobot_karung_dinamis and any(m.berat_kg is None for m in r.pemindahan_karung if m.selama_proses and m.dibatalkan_pada is None) else float(r.berat_masuk_kg),
            sisa=float(r.berat_akhir_kg) if r.berat_akhir_kg is not None else None,
            terpakai=float(r.berat_terpakai_kg) if r.berat_terpakai_kg is not None and (not r.bobot_karung_dinamis or bobot_pemakaian([r]).diketahui and bobot_pemakaian([r]).tak_diketahui == 0) else None,
            dinamis=r.bobot_karung_dinamis) for r, nama in rows],
        sisa_lengkap=lengkap, bahan=bobot.teks() if bobot else 'Belum dapat dipastikan · periksa sisa silo',
        bobot_final=bobot.pasti if bobot else False,
        hasil=[dict(jenis=j, nama=nama_produk(j), kg=hasil.get(j), beras=j in p.GRADES)
               for j in [*(j for j in reversed(p.GRADES) if j != 'beras_b'), 'beras_b', *p.BYPRODUCTS]],
        ada_hasil=bool(hasil), beras=neraca.beras.kg if hasil else None,
        samping=sum(x.kg for x in neraca.samping) if hasil else None,
        total=neraca.keluar_kg if hasil else None,
        selisih=neraca.susut.kg if hasil and bobot and bobot.pasti else None,
        rendemen=await p.rendemen_proses(db, proc.id) if lengkap else None,
        detail=f'/riwayat-sosoh/{proc.id}' if proc.status == 'selesai' else
            f'/proses-aktif/sosoh/{proc.kode_proses}')
