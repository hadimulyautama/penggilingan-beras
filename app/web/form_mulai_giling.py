"""Pembaca formulir mulai giling; tidak mengklaim sumber atau menggabung jasa."""
from sqlalchemy import select

from app.models import Jasa, Pelanggan
from app.penggilingan.gudang1.services import silo as si
from app.penggilingan.gudang1.services.bobot import jumlah
from app.services.jasa import cocok_pemilik, nama_pemilik


async def baca_silo(db, silo):
    rows = await si._silo_active_rows(db, silo.id)
    bobot = jumlah([await si._row_bobot(db, r) for r in rows])
    rinci = await si.isi_silo(db, silo.id)
    pemilik = []
    for jid in dict.fromkeys(r.jasa_id for r in rows):
        nama = await db.scalar(select(Pelanggan.nama_pelanggan).join(
            Jasa, Jasa.pelanggan_id == Pelanggan.id).where(Jasa.id == jid)) if jid else "Pabrik"
        pemilik.append(nama or await nama_pemilik(db, jid) or "Pemilik belum tercatat")
    pemilik = list(dict.fromkeys(pemilik))
    pesanan = (await db.scalars(select(Jasa.kode).where(
        Jasa.id.in_({r.jasa_id for r in rows if r.jasa_id}))
        .order_by(Jasa.id))).all()
    jalan = await si.giling_berjalan_untuk_silo(db, silo.id)
    data = dict(nama=silo.nama_silo, bobot=bobot.teks() if rows else "Tidak ada bahan",
                pemilik=" · ".join(pemilik), pesanan=list(pesanan),
                jumlah_sumber=len(rows),
                asal=list(dict.fromkeys(si.label_asal(x.asal, x.jasa_id) for x in rinci)),
                siap=bool(rows) and jalan is None,
                proses=jalan.kode_proses if jalan else None,
                detail=f"/proses-aktif/giling/{jalan.kode_proses}" if jalan else None)
    return data, rows


async def ringkasan(db, pilihan):
    # Ikuti normalisasi/urutan aksi; tidak menyimpulkan pemilik dari namanya.
    pilihan = list(dict.fromkeys(str(x).strip().upper() for x in pilihan if str(x or "").strip()))
    silos, rows, peringatan = [], [], []
    for nama in pilihan:
        silo = await si.get_g1_silo(db, nama)
        if silo is None:
            silos.append(dict(nama=f"Silo {nama}", bobot="Belum tersedia", siap=False,
                              proses=None, detail=None))
            peringatan.append(f"Silo {nama} Gudang 1 tidak ditemukan atau tidak aktif.")
            continue
        data, bahan = await baca_silo(db, silo)
        silos.append(data)
        rows.extend(bahan)
        if not data['siap']:
            peringatan.append(f"{silo.nama_silo} sedang digiling ({data['proses']}). Lepaskan centangnya untuk memilih bahan lain."
                              if data['proses'] else f"{silo.nama_silo} sudah tidak berisi bahan.")
    pemilik_ids = list(dict.fromkeys(r.jasa_id for r in rows))
    cocok = all([await cocok_pemilik(db, pemilik_ids[0], j) for j in pemilik_ids[1:]]) if pemilik_ids else True
    if not cocok:
        peringatan.append("Kepemilikan berbeda tidak boleh digabung: bahan pabrik dan jasa, atau pelanggan berbeda. Perbaiki pilihan silo.")
    elif len(pemilik_ids) > 1:
        peringatan.append("Pesanan berbeda milik pelanggan yang sama akan digabung otomatis oleh layanan saat mulai giling disimpan.")
    total = jumlah([await si._row_bobot(db, r) for r in rows]) if rows else None
    return dict(pilihan=pilihan, silos=silos, bobot=total.teks() if total else "Belum tersedia",
                final=total.pasti if total else False, jumlah_sumber=len(rows),
                pemilik=" · ".join(dict.fromkeys(d.get('pemilik', '') for d in silos if d.get('pemilik'))) if cocok else "Kepemilikan belum cocok",
                cocok=cocok, siap=bool(silos) and all(d['siap'] for d in silos) and cocok,
                peringatan=peringatan)
