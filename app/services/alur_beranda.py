"""Keadaan alat Beranda dari master dan saldo layanan operasional.

Warna 80% adalah simbol terisi yang diminta pemilik, bukan sensor ketinggian.
Bobot yang belum diketahui tetap disebut menunggu timbang, bukan nol.
"""
from __future__ import annotations

from urllib.parse import urlencode
from sqlalchemy import select

from app.models import Silo, Warehouse, SetelanPabrik
from app.penggilingan.gudang1.services import drying, silo as sg1
from app.penggilingan.gudang1.services.bobot import dari_batches
from app.penggilingan.gudang2.service import hitung_stok_silo

K_TUNGKU = 'tungku_dryer:'


async def peta_tungku(db):
    rows = (await db.execute(select(SetelanPabrik.kunci, SetelanPabrik.nilai)
                            .where(SetelanPabrik.kunci.startswith(K_TUNGKU, autoescape=True)))).all()
    return {int(k[len(K_TUNGKU):]): v for k, v in rows
            if k[len(K_TUNGKU):].isdigit() and v.strip()}


async def simpan_tungku(db, dryer_id, nama, *, user):
    """Pemetaan fisik disimpan eksplisit; nama sama berarti tungku bersama."""
    from sqlalchemy.dialects.postgresql import insert
    from app.services.activity_log import log_activity
    nama = ' '.join(nama.split())
    if len(nama) > 50:
        raise ValueError('Nama tungku maksimal 50 karakter.')
    uid = user.id if user is not None else None
    key = K_TUNGKU + str(dryer_id)
    lama = await db.get(SetelanPabrik, key)
    sebelum = lama.nilai if lama else None
    await db.execute(insert(SetelanPabrik).values(kunci=key, nilai=nama, diubah_oleh=uid)
                     .on_conflict_do_update(index_elements=['kunci'],
                                           set_={'nilai': nama, 'diubah_oleh': uid}))
    await log_activity(db, table_name='setelan_pabrik', record_id=0, action='UPDATE',
                       changed_by=uid, field_name=key, old_value=sebelum, new_value=nama)


def fase_dryer(lot, ada_batch):
    if lot is None:
        return ('terisi', 'Menunggu mulai') if ada_batch else ('kosong', 'Tidak berjalan')
    if lot.status == 'proses':
        return 'mengeringkan', 'Mengeringkan'
    if lot.waktu_selesai_pendinginan is not None:
        return 'terisi', 'Dingin · menunggu keluar'
    return 'pendinginan', 'Pendinginan'


async def daftar_dryer(db):
    peta = await peta_tungku(db)
    kelompok = {}
    for d in await drying.dryers_g1(db):
        lot = await drying.active_drying_lot(db, d.id)
        batches = (await drying._lot_batches(db, lot.id) if lot
                   else await drying._loose_dryer_batches(db, d.id))
        bobot = dari_batches(batches)
        mode, proses = fase_dryer(lot, bool(batches))
        terisi = lot is not None or bool(batches)
        # Status jeda bukan mesin menyala. Dibaca dari log jeda, seperti detail.
        if lot and lot.status == 'proses':
            from app.penggilingan.gudang1.services.jeda import jeda_terbuka
            if await jeda_terbuka(db, 'pengeringan', lot.id):
                mode, proses = 'terisi', 'Pengeringan dijeda'
        nama_tungku = peta.get(d.id, '')
        key = nama_tungku.casefold() if nama_tungku else ''
        kelompok.setdefault(key, {'nama': nama_tungku, 'dryers': []})
        if lot:
            jenis = 'pengeringan' if lot.status == 'proses' else 'pendinginan'
            href = (f'/riwayat-pengeringan/{lot.id}' if lot.waktu_selesai_pendinginan
                    else f'/proses-aktif/{jenis}/{lot.kode_lot}')
        else:
            href = '/pekerjaan?' + urlencode({'gudang': 'g1', 'jenis': 'pengeringan', 'tab': 'tindakan'})
        kelompok[key]['dryers'].append(dict(
            id=d.id, nama=d.nama, terisi=terisi, mode=mode, proses=proses,
            bobot=bobot.teks() if terisi else '0 kg',
            kondisi_alat=d.status, kapasitas=float(d.kapasitas_kg or 0),
            kode=lot.kode_lot if lot else '', href=href))
    return list(kelompok.values())


async def daftar_silo(db, gid):
    silos = (await db.execute(select(Silo).join(Warehouse)
        .where(Warehouse.kode_fungsi == gid, Warehouse.aktif.is_(True), Silo.aktif.is_(True))
        .order_by(Silo.nama_silo, Silo.id))).scalars().all()
    out = []
    for s in silos:
        if gid == 'g1':
            rows = await sg1._silo_active_rows(db, s.id)
            bobot = await sg1._silo_content_bobot(db, s.id)
            terisi = bool(rows) and (not bobot.pasti or bobot.angka() > 0.001)
            kg = bobot.angka()
            teks = bobot.teks() if terisi else '0 kg'
        else:
            kg = float(await hitung_stok_silo(db, s.id))
            terisi = kg > 0.001
            teks = f'{kg:,.0f} kg'.replace(',', '.')
        out.append(dict(id=s.id, nama=s.nama_silo, terisi=terisi, kg=kg, bobot=teks))
    return out


async def bangun(db, view, operasional):
    from app.web.layar import GUDANG, boleh_lihat_gudang, _petak_g1, _petak_g2
    out = []
    for gid, nama, fungsi in GUDANG:
        if not boleh_lihat_gudang(view, gid):
            continue
        silos = await daftar_silo(db, gid)
        dryers = await daftar_dryer(db) if gid == 'g1' else []
        sel = _petak_g1(operasional) if gid == 'g1' else await _petak_g2(db)
        incoming, proses, _, stok = sel
        jenis = 'pengeringan' if gid == 'g1' else 'sosoh'
        langkah = [dict(nama='Gabah masuk' if gid == 'g1' else 'PK masuk',
                         ket=incoming['ket'].split(' · ')[0], href='/barang-masuk?gudang='+gid),
                   dict(nama='Pengeringan' if gid == 'g1' else 'Penyosohan',
                        ket=str(proses['nilai'])+proses['sat'],
                        href=f'/pekerjaan?gudang={gid}&jenis={jenis}&tab=berjalan')]
        if gid == 'g1':
            langkah.append(dict(nama='Giling', ket=str(len(operasional.get('giling', [])))+' proses',
                                href='/pekerjaan?gudang=g1&jenis=giling&tab=berjalan'))
        langkah.append(dict(nama='Stok PK' if gid == 'g1' else 'Tumpukan PK',
                            ket=stok['nilai']+stok['sat'], href='/stok?gudang='+gid))
        out.append(dict(id=gid, nama=nama, fungsi=fungsi, silos=silos, dryers=dryers,
                        terisi=sum(s['terisi'] for s in silos),
                        dryer_total=sum(len(g['dryers']) for g in dryers),
                        dryer_terisi=sum(d['terisi'] for g in dryers for d in g['dryers']),
                        masuk=incoming, stok=stok, langkah=langkah))
    return out
