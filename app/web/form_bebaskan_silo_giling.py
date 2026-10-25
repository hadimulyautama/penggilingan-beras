"""Pembaca formulir G1: tidak memulihkan sumber lama atau melepas klaim.

Angka siklus memakai snapshot sumber yang juga diperiksa layanan pembebasan;
saldo fisik terkini tetap memakai pembaca silo, bukan jumlah riwayat sumber.
"""
from app.models import Jasa, MillingProcess, Silo
from app.web.form_selesai_giling import ringkasan as konteks_proses
from app.penggilingan.gudang1.services.silo import silo_ids_proses, _silo_content_bobot


async def ringkasan(db, *, kode_proses, silo="", sisa=None, auto_satu=False):
    data = await konteks_proses(db, kode_proses=kode_proses)
    proc = await db.get(MillingProcess, data['id'])
    jasa = await db.get(Jasa, proc.jasa_id) if proc.jasa_id else None
    normal = lambda nama: (nama or '').strip().casefold().removeprefix('silo ').strip()
    terbuka = [x for x in data['sumber'] if x['sisa'] is None]
    nama_terbuka = list(dict.fromkeys(x['silo'] for x in terbuka))
    if auto_satu and not silo and len(nama_terbuka) == 1:
        silo = nama_terbuka[0]
    dipilih = [x for x in terbuka if normal(x['silo']) == normal(silo)] if silo else []
    tahu = bool(dipilih) and all(x['bobot'] is not None for x in dipilih)
    bahan = sum(x['bobot'] for x in dipilih) if tahu else None
    # Bantuan baca saja; kelayakan angka dan token tetap diperiksa endpoint lama.
    terpakai = bahan - sisa if bahan is not None and sisa is not None and 0 <= sisa <= bahan else None
    sekarang = []
    for sid in await silo_ids_proses(db, proc):
        benda = await db.get(Silo, sid)
        bobot = await _silo_content_bobot(db, sid)
        sekarang.append(dict(silo=benda.nama_silo, status=benda.status, bobot=bobot.teks()))
    return dict(kode_proses=data['kode_proses'], id=data['id'], pemilik=data['pemilik'],
        kepemilikan=data['kepemilikan'], pesanan=jasa.kode if jasa else None,
        status=data['status'], sebab_jeda=data['sebab_jeda'], mulai=data['mulai'],
        bobot_final=data['bobot_final'], sumber=dipilih, sumber_proses=data['sumber'],
        silo=dipilih[0]['silo'] if dipilih else silo, bahan=bahan, sisa=sisa,
        terpakai=terpakai, terbuka=bool(dipilih), silo_sekarang=sekarang,
        hasil_pk=data['tercatat'], stok_pk=data['stok_sebelum'], detail=data['detail'])
