"""Koreksi transfer generik: tumpukan dahulu, lalu silo dan bahan sosoh.

Pratinjau tidak menulis. Rancangan dihitung lagi di bawah kunci stok saat
simpan; tanda tangan mengikat angka, pemakaian, hasil proses, dan pelaku.
Hasil terukur tidak diskalakan untuk menyembunyikan salah catat bahan.
"""
from __future__ import annotations

import copy
import hmac
import json
import re
from datetime import datetime
from decimal import Decimal as D
from sqlalchemy import DateTime, Numeric, select, func
from app.database import now_local
from app.models import (Peristiwa, PermintaanPk, PengirimanPk, PengirimanPkItem,
                        InternalTransfer, PkGudang2Intake, PolishingSiloUsage,
                        PolishingProcess, PkTumpukanToSilo, Silo)
from app.services import pengiriman_pk as kirim, peristiwa as buku
from app.services import pk_koreksi_rantai as rantai
from app.services.koreksi_bahan_berjalan import raw
from app.services.kepemilikan import sign, InventoryError

JENIS = 'koreksi_transfer_pk'
MODELS = {'permintaan': PermintaanPk, 'items': PengirimanPkItem, 'pengiriman': PengirimanPk}


def angka(value, nama, *, nol=True, presisi=2):
    from decimal import InvalidOperation
    try:
        n = D(str(value))
        if isinstance(value, bool) or not n.is_finite() or n < 0 or n > D('9999999999.99') or not nol and n == 0:
            raise ValueError
        if n != n.quantize(D('.01')):
            raise ValueError
        return n
    except (InvalidOperation, ValueError, TypeError):
        raise kirim.PengirimanError(f'{nama} harus berupa kg yang sah, maksimal dua desimal.') from None


def snapshot(row):
    return buku.bersih(raw(row))


def perubahan(row, **values):
    before = snapshot(row)
    return dict(id=row.id, before=before, after={**copy.deepcopy(before), **values})


class Rancangan(rantai.Rancangan):
    async def usage(self, db, u, delta, col):
        """Sisa silo didahulukan; hanya kekurangannya mengubah bahan terpakai.

        Sisa siklus lama dapat menjadi awal siklus berikutnya. Penurunan
        diteruskan, sehingga tidak menciptakan bahan baru di siklus berikut.
        Penambahan bahan historis mempertahankan sisa yang telah dicatat.
        """
        item = self.row('usages', u)
        after = item['after']
        original = D(str(u.berat_awal_kg)) + D(str(u.berat_masuk_kg))
        total = self.totals.get(u.id, original) + delta
        if total < 0:
            raise kirim.PengirimanError('Koreksi membuat bahan silo negatif. Periksa pemindahan terkait.')
        if col:
            after[col] = str(D(str(after[col] or 0)) + delta)
            if D(after[col]) < 0:
                raise kirim.PengirimanError('Koreksi melebihi kontribusi bahan pada siklus silo ini.')
        self.totals[u.id] = total
        proc = await db.get(PolishingProcess, u.polishing_process_id)
        self.procs[proc.id] = proc
        self.silos.add(u.silo_id)
        item.update(kode=proc.kode_proses, total_before=str(original), total_after=str(total))
        if after['berat_akhir_kg'] is not None:
            oldtail = D(str(after['berat_akhir_kg']))
            tail = max(D(0), oldtail + min(D(0), delta))
            after['berat_akhir_kg'] = str(tail)
            after['terpakai_lama_kg'] = str(total - tail)
            if tail != oldtail:
                nxt = await db.scalar(select(PolishingSiloUsage).where(
                    PolishingSiloUsage.silo_id == u.silo_id, PolishingSiloUsage.id > u.id)
                    .order_by(PolishingSiloUsage.id).limit(1))
                if nxt:
                    await self.usage(db, nxt, tail - oldtail, 'awal_tetap_kg')


def isian(req):
    key = req.get('kunci', '')
    reason = (req.get('alasan') or '').strip()
    if not re.fullmatch(r'[a-f0-9]{32}', key):
        raise kirim.PengirimanError('Kunci koreksi tidak sah.')
    if not reason or len(reason) > 2000:
        raise kirim.PengirimanError('Isi alasan koreksi, maksimal 2.000 karakter.')
    return dict(aksi=req.get('aksi'), berat_kg=req.get('berat_kg'), tujuan=req.get('tujuan'),
                pemindahan_id=req.get('pemindahan_id'), alasan=reason, kunci=key)


async def _aktif_lain(db, r):
    return await db.scalar(select(PermintaanPk.id).where(
        PermintaanPk.milling_process_id == r.milling_process_id,
        PermintaanPk.jasa_id == r.jasa_id, PermintaanPk.id != r.id,
        PermintaanPk.status.in_(['diminta', 'disetujui', 'dikirim'])).limit(1))


async def rancang_permintaan(db, rid, req, user):
    r = await db.get(PermintaanPk, rid, populate_existing=True)
    if not r:
        raise kirim.PengirimanError('Permintaan tidak ditemukan.')
    if r.internal_transfer_id and not r.bertahap:
        raise kirim.PengirimanError('Permintaan lama mempunyai transfer. Buka rincian transfer lamanya.')
    from app.services.transfer import pending_transfer_kg
    allocated = await kirim.terpakai(db, rid)
    completed = await kirim.terpakai(db, rid, selesai=True)
    if allocated != completed:
        raise kirim.PengirimanError('Selesaikan perjalanan timbang lama sebelum mengoreksi permintaan.')
    free = D(str(await pending_transfer_kg(db, r.milling_process_id, pemilik_id=r.jasa_id, bebas=True)))
    held = max(D(0), D(str(r.berat_setuju_kg or 0)) - allocated) if r.bertahap and r.status in ('disetujui', 'dikirim') else D(0)
    changes = dict(sebab='Koreksi Admin: ' + req['alasan'])
    action = req['aksi']
    if action == 'minta':
        if r.status != 'diminta':
            raise kirim.PengirimanError('Jumlah permintaan hanya diubah sebelum disetujui.')
        changes['berat_minta_kg'] = str(angka(req['berat_kg'], 'Jumlah permintaan', nol=False, presisi=2))
    elif action in ('batal', 'kembali'):
        if allocated:
            raise kirim.PengirimanError('Masih ada transfer aktif. Koreksi transfer terkait atau tutup sisa persetujuan.')
        if r.status not in ('diminta', 'disetujui', 'dikirim'):
            raise kirim.PengirimanError('Permintaan sudah ditutup. Gunakan buka kembali bila sisanya masih diperlukan.')
        changes.update(status='gugur' if action == 'batal' else 'diminta',
                       berat_final_kg=0 if action == 'batal' else None,
                       ditutup_oleh=user.id if action == 'batal' else None,
                       waktu_tutup=now_local().isoformat() if action == 'batal' else None)
        if action == 'kembali':
            changes.update(berat_setuju_kg=None, tujuan=None, silo_id=None,
                           disetujui_oleh=None, waktu_setuju=None, bertahap=True)
    elif action in ('persetujuan', 'buka'):
        value = angka(req['berat_kg'] if action == 'persetujuan' else r.berat_setuju_kg,
                      'Jumlah disetujui', nol=False, presisi=2)
        if action == 'buka' and r.status not in ('selesai', 'gugur'):
            raise kirim.PengirimanError('Hanya sisa persetujuan yang sudah ditutup dapat dibuka kembali.')
        if not r.berat_setuju_kg or r.status == 'diminta':
            raise kirim.PengirimanError('Gunakan Setujui permintaan untuk persetujuan pertama.')
        if value < allocated:
            raise kirim.PengirimanError('Persetujuan tidak boleh lebih kecil dari transfer aktif. Koreksi transfer dahulu.')
        if value - allocated > free + held:
            raise kirim.PengirimanError('Stok bebas tidak mencukupi sisa persetujuan baru.')
        if action == 'buka' and value == allocated:
            raise kirim.PengirimanError('Tidak ada sisa persetujuan yang dapat dibuka.')
        if value > allocated and await _aktif_lain(db, r):
            raise kirim.PengirimanError('Lot sudah mempunyai permintaan aktif lain. Lanjutkan permintaan tersebut.')
        if req.get('tujuan'):
            from app.penggilingan.gudang2.service import _tujuan_and_silo
            target, sid = await _tujuan_and_silo(db, req['tujuan'])
            if allocated and (target != r.tujuan or sid != r.silo_id):
                raise kirim.PengirimanError('Tujuan transfer yang sudah tercatat tetap. Tutup sisa, lalu minta tujuan baru.')
            if sid:
                from app.services.jasa import cocok_pemilik, pemilik_silo_g2
                if not all([await cocok_pemilik(db, r.jasa_id, o) for o in await pemilik_silo_g2(db, sid)]):
                    raise kirim.PengirimanError('Pemilik silo tujuan berbeda dari lot.')
            changes.update(tujuan=target, silo_id=sid)
        changes.update(bertahap=True, berat_setuju_kg=str(value),
                       status='selesai' if value == allocated else 'dikirim' if allocated else 'disetujui',
                       berat_final_kg=str(completed) if value == allocated else None,
                       waktu_tutup=r.waktu_tutup.isoformat() if value == allocated and r.waktu_tutup else None,
                       ditutup_oleh=None)
    else:
        raise kirim.PengirimanError('Pilih tindakan koreksi permintaan yang sah.')
    afterheld = max(D(0), D(str(changes.get('berat_setuju_kg', r.berat_setuju_kg) or 0)) - allocated) if changes.get('status', r.status) in ('disetujui', 'dikirim') else D(0)
    return dict(permintaan=[perubahan(r, **changes)], items=[], pengiriman=[],
                pk_chain={}, stok_bebas_sebelum=str(free), dicadangkan_sebelum=str(held),
                stok_bebas_sesudah=str(free + held - afterheld), dicadangkan_sesudah=str(afterheld),
                selesai_sebelum=str(completed), penjelasan='Koreksi permintaan mengubah kebutuhan atau cadangan; belum memindahkan stok fisik.')


async def rancang_transfer(db, iid, req, user):
    i = await db.get(PengirimanPkItem, iid, populate_existing=True)
    j = await db.get(PengirimanPk, i.pengiriman_id, populate_existing=True) if i else None
    if not j or j.pakai_kendaraan or j.status != 'selesai' or not i.internal_transfer_id:
        raise kirim.PengirimanError('Pilih transfer generik yang masih aktif; perjalanan timbang lama memakai pemeriksaan tiket.')
    if req['aksi'] not in ('jumlah', 'bahan'):
        raise kirim.PengirimanError('Pilih koreksi jumlah transfer.')
    t = await db.get(InternalTransfer, i.internal_transfer_id, populate_existing=True)
    it = await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.internal_transfer_id == t.id)) if t else None
    old = D(str(i.berat_kg))
    target = old if req['aksi'] == 'bahan' else angka(req['berat_kg'], 'Jumlah transfer', presisi=2)
    if not t or t.status != 'terkirim' or not it or D(str(t.berat_kg)) != old or D(str(it.berat_kg)) != old:
        raise kirim.PengirimanError('Bobot transfer, muatan, dan pemasukan tidak sama. Periksa koreksi asal sebelum melanjutkan.')
    reason = await rantai.alasan_perubahan_terpisah(db, 'transfers', t.id)
    if reason:
        raise kirim.PengirimanError(reason)
    if target == old and req['aksi'] == 'jumlah':
        raise kirim.PengirimanError('Tidak ada perubahan jumlah transfer.')
    # Sumber berpengalihan mempunyai arus FIFO sendiri. Jangan mengubah
    # jumlah transfer terpisah lalu membuat bagian kepemilikan tak bersumber.
    from app.services import pk_persediaan
    if await pk_persediaan.ada_pengalihan(db, sumber='giling:' + str(t.milling_process_id)):
        raise kirim.PengirimanError('Lot mempunyai pengalihan kepemilikan. Gunakan koreksi AM-PK terkait untuk menjaga jejak pemilik.')
    if req['aksi'] == 'bahan':
        return await rancang_bahan(db, i=i, j=j, t=t, it=it, req=req, user=user)
    r = await db.get(PermintaanPk, i.permintaan_id, populate_existing=True)
    allocated = await kirim.terpakai(db, r.id)
    completed = await kirim.terpakai(db, r.id, selesai=True)
    if completed != allocated:
        raise kirim.PengirimanError('Selesaikan perjalanan lama pada permintaan ini dahulu.')
    effective = completed - old + target
    if effective > D(str(r.berat_setuju_kg)):
        raise kirim.PengirimanError('Total koreksi melebihi persetujuan. Koreksi jumlah persetujuan Admin dahulu.')
    from app.services.transfer import pending_transfer_kg, saldo_pk
    free = D(str(await pending_transfer_kg(db, t.milling_process_id, pemilik_id=t.jasa_id, bebas=True)))
    held = max(D(0), D(str(r.berat_setuju_kg)) - allocated) if r.status in ('disetujui', 'dikirim') else D(0)
    if target - old > free + held:
        raise kirim.PengirimanError('Stok asal tidak mencukupi tambahan transfer; cadangan transaksi lain dipertahankan.')
    plan = Rancangan()
    plan.user = user
    from app.services.pk_50 import bagi_tersimpan
    bags, bulk = bagi_tersimpan(target, 2)
    tr = plan.row('transfers', t)
    if target:
        tr['after'].update(berat_kg=str(target), jumlah_karung=bags, berat_curah_kg=str(bulk))
    else:
        tr['after']['status'] = 'dibatalkan'
    tr.update(effective_before=str(old), effective_after=str(target), kode=t.kode_transfer)
    await plan.intake(db, it, old - target)
    # Pemasukan yang dibatalkan mempertahankan bobot historisnya; pembaca
    # stok menyaring dibatalkan_pada. Muatan efektif transfer menjadi nol.
    if req.get('pemindahan_id'):
        if target <= old or it.silo_id:
            raise kirim.PengirimanError('Pemindahan dipilih hanya untuk tambahan transfer dari tumpukan yang memang sudah masuk silo.')
        move = await db.get(PkTumpukanToSilo, req['pemindahan_id'], populate_existing=True)
        if not move or move.dibatalkan_pada or move.pk_gudang2_intake_id != it.id:
            raise kirim.PengirimanError('Pemindahan silo bukan bagian transfer ini atau sudah dibatalkan.')
        amount = D(str(move.berat_kg)) + target - old
        mr = plan.row('moves', move)
        nb, bc = bagi_tersimpan(amount, 3)
        mr['after'].update(jumlah_karung=None, berat_timbang_kg=str(amount), jumlah_karung_50=nb, berat_curah_kg=str(bc))
        mr.update(effective_before=str(move.berat_kg), effective_after=str(amount))
        from app.services.koreksi_bahan_berjalan import siklus_g2
        usage = await siklus_g2(db, move)
        await plan.silo(db, move, target - old, dynamic=bool(usage and move.pemakaian_silo_id == usage.id))
    chain = await plan.selesai(db)
    chain['linkage_version'] = 2
    # Proses aktif boleh sementara mempunyai hasil melebihi bahan: operator
    # masih bisa melengkapi bahan. Penutupan normal tetap menolak keadaan itu.
    for proc in chain['processes']:
        proc['susut_before'] = str(D(proc['bahan_before']) - D(proc['hasil_tercatat']))
        proc['susut_after'] = str(D(proc['bahan_after']) - D(proc['hasil_tercatat']))
        if proc['status'] == 'selesai' and D(proc['hasil_tercatat']) > D(proc['bahan_after']):
            raise kirim.PengirimanError(f"{proc['kode']}: hasil tercatat melebihi bahan setelah koreksi. Lengkapi bahan sebenarnya atau koreksi hasil yang salah sebelum menyimpan; hasil tidak diskalakan otomatis.")
    # Permintaan yang sudah ditutup tidak dibuka diam-diam oleh koreksi
    # fakta. Permintaan aktif tetap menyimpan cadangan sisanya seperti semula.
    closed = r.status in ('selesai', 'gugur') or effective == D(str(r.berat_setuju_kg))
    newstatus = ('selesai' if effective else 'gugur') if closed else ('dikirim' if effective else 'disetujui')
    remaining_items = list((await db.scalars(select(PengirimanPkItem).where(PengirimanPkItem.pengiriman_id == j.id))).all())
    all_zero = all(x.id == i.id or D(str(x.berat_kg)) == 0 for x in remaining_items) and not target
    pile_before = None
    pile_after = None
    if not it.silo_id:
        source = (await pk_persediaan.baca(db)).get('tumpukan:' + str(it.id))
        if source:
            pile_before = source.bebas(it.jasa_id)
            pile_after = max(D(0), pile_before + target - old)
            if req.get('pemindahan_id'):
                pile_after = pile_before
    physical = D(str(await saldo_pk(db, t.milling_process_id)))
    afterheld = D(0) if closed else D(str(r.berat_setuju_kg)) - effective
    return dict(permintaan=[perubahan(r, status=newstatus,
                 berat_kirim_kg=str(effective), berat_final_kg=str(effective) if closed else None,
                 waktu_tutup=now_local().isoformat() if closed else None,
                 ditutup_oleh=user.id if closed else None,
                 sebab='Koreksi transfer. ' + req['alasan'])],
                items=[perubahan(i, berat_kg=str(target))],
                pengiriman=[perubahan(j, status='dibatalkan' if all_zero else 'selesai')],
                pk_chain=chain, stok_bebas_sebelum=str(free),
                stok_asal_before=str(physical), stok_asal_after=str(physical + old - target),
                dicadangkan_sebelum=str(held), dicadangkan_sesudah=str(afterheld),
                stok_bebas_sesudah=str(free + old - target + held - afterheld),
                tumpukan_before=None if pile_before is None else str(pile_before),
                tumpukan_after=None if pile_after is None else str(pile_after),
                konteks_items=[snapshot(x) for x in remaining_items],
                penjelasan='Pengurangan memakai sisa tumpukan dahulu, lalu sisa silo dan bahan proses terkait. Tambahan tetap di tumpukan kecuali pemindahan silo terkait dipilih. Hasil produksi tetap; susut dan rendemen mengikuti bahan efektif. Permintaan aktif tetap aktif; permintaan yang sudah ditutup hanya dibuka kembali oleh Admin.')


async def rancang_bahan(db, *, i, j, t, it, req, user):
    """Kekurangan catat bahan memakai tumpukan yang SUDAH ditransfer dulu.

    Mengubah bahan bukan bukti ada perpindahan tambahan dari Gudang 1.
    Hanya bila transfer asal sendiri salah, jumlah transfer dikoreksi juga.
    """
    from app.services import pk_persediaan
    if it.silo_id or not req.get('pemindahan_id'):
        raise kirim.PengirimanError('Pilih pemindahan tumpukan ke silo yang benar.')
    move = await db.get(PkTumpukanToSilo, req['pemindahan_id'], populate_existing=True)
    if not move or move.dibatalkan_pada or move.pk_gudang2_intake_id != it.id:
        raise kirim.PengirimanError('Pemindahan silo bukan bagian transfer ini atau sudah dibatalkan.')
    reason = await rantai.alasan_perubahan_terpisah(db, 'moves', move.id)
    if reason:
        raise kirim.PengirimanError(reason)
    if await pk_persediaan.ada_pengalihan(db, sumber='tumpukan:' + str(it.id)):
        raise kirim.PengirimanError('Tumpukan mempunyai pengalihan kepemilikan. Gunakan koreksi AM-PK terkait.')
    source = (await pk_persediaan.baca(db)).get('tumpukan:' + str(it.id))
    if not source or source.masalah:
        raise kirim.PengirimanError('Saldo tumpukan tidak dapat dibuktikan.')
    before = source.bebas(it.jasa_id)
    old = D(str(move.berat_kg))
    target = angka(req['berat_kg'], 'Jumlah pemindahan ke silo')
    delta = target - old
    if not delta:
        raise kirim.PengirimanError('Tidak ada perubahan jumlah yang masuk silo.')
    if delta > before:
        raise kirim.PengirimanError('Sisa tumpukan tidak cukup untuk tambahan bahan. Periksa jumlah transfer atau sumber bahan yang sebenarnya dahulu.')
    plan = Rancangan()
    plan.user = user
    if delta < 0:
        await plan.move(db, move, -delta)
    else:
        from app.services.pk_50 import bagi_tersimpan
        nb, bc = bagi_tersimpan(target, 3)
        mr = plan.row('moves', move)
        mr['after'].update(jumlah_karung=None, berat_timbang_kg=str(target), jumlah_karung_50=nb, berat_curah_kg=str(bc))
        mr.update(effective_before=str(old), effective_after=str(target))
        from app.services.koreksi_bahan_berjalan import siklus_g2
        usage = await siklus_g2(db, move)
        await plan.silo(db, move, delta, dynamic=bool(usage and move.pemakaian_silo_id == usage.id))
    chain = await plan.selesai(db)
    for proc in chain['processes']:
        proc['susut_before'] = str(D(proc['bahan_before']) - D(proc['hasil_tercatat']))
        proc['susut_after'] = str(D(proc['bahan_after']) - D(proc['hasil_tercatat']))
        if proc['status'] == 'selesai' and D(proc['hasil_tercatat']) > D(proc['bahan_after']):
            raise kirim.PengirimanError(f"{proc['kode']}: hasil tercatat melebihi bahan setelah koreksi. Periksa jumlah bahan/hasil sebenarnya.")
    from app.services.transfer import saldo_pk, pending_transfer_kg
    physical = await saldo_pk(db, t.milling_process_id)
    free = await pending_transfer_kg(db, t.milling_process_id, pemilik_id=t.jasa_id, bebas=True)
    r = await db.get(PermintaanPk, i.permintaan_id, populate_existing=True)
    return dict(permintaan=[], items=[], pengiriman=[], pk_chain=chain,
                konteks_permintaan=snapshot(r), konteks_transfer=snapshot(t),
                konteks_item=snapshot(i), konteks_pengiriman=snapshot(j),
                stok_asal_before=str(physical), stok_asal_after=str(physical),
                stok_bebas_sebelum=str(free), stok_bebas_sesudah=str(free),
                tumpukan_before=str(before), tumpukan_after=str(before - delta),
                penjelasan='Jumlah transfer asal tetap. Tambahan bahan mengambil sisa tumpukan yang sudah tersedia; pengurangan bahan kembali menjadi tumpukan. Bahan, sisa silo, susut, dan rendemen proses terkait dihitung ulang. Hasil produksi tetap sesuai hasil timbang.')


async def rancang(db, *, jenis, ident, req, user):
    kirim.admin(user)
    clean = isian(req)
    if jenis == 'permintaan':
        plan = await rancang_permintaan(db, ident, clean, user)
    elif jenis == 'transfer':
        plan = await rancang_transfer(db, ident, clean, user)
    else:
        raise kirim.PengirimanError('Jenis koreksi tidak dikenal.')
    # Jam pemeriksaan bukan bagian sidik: waktu simpan akan ditetapkan pada
    # event koreksi, bukan membuat dua pratinjau identik dianggap berbeda.
    for item in plan['permintaan']:
        if item['after'].get('waktu_tutup') != item['before'].get('waktu_tutup'):
            item['after']['waktu_tutup'] = rantai.SAAT if item['after'].get('waktu_tutup') else None
    return clean, buku.bersih(plan)


def tanda(jenis, ident, user, clean, plan):
    return sign([jenis, ident, user.id, clean, plan])


async def periksa(db, *, jenis, ident, req, user):
    clean, plan = await rancang(db, jenis=jenis, ident=ident, req=req, user=user)
    return dict(rancangan=plan, pemeriksaan=tanda(jenis, ident, user, clean, plan))


async def _terapkan_baris(db, event, user):
    from app.services.activity_log import log_activity
    for kind, model in MODELS.items():
        for item in event.muatan['rancangan'][kind]:
            row = await db.get(model, item['id'], populate_existing=True, with_for_update=True)
            if snapshot(row) != item['before']:
                raise kirim.PengirimanError('Data berubah sejak pemeriksaan; periksa ulang.')
            for key, value in item['after'].items():
                if value == item['before'].get(key):
                    continue
                col = row.__mapper__.attrs[key].columns[0]
                if value == rantai.SAAT:
                    value = event.waktu
                elif value is not None and isinstance(col.type, Numeric):
                    value = D(str(value))
                elif value is not None and isinstance(col.type, DateTime):
                    value = datetime.fromisoformat(value)
                setattr(row, key, value)
            await log_activity(db, table_name=model.__tablename__, record_id=row.id,
                action='UPDATE', changed_by=user.id, old_value=json.dumps(item['before']),
                new_value=json.dumps(snapshot(row)), alasan=event.muatan['isian']['alasan'], aksi=JENIS)
    await db.flush()


async def simpan(db, *, jenis, ident, req, user):
    kirim.admin(user)
    clean = isian(req)
    await kirim.kunci_stok(db)
    key = f'{JENIS}:{user.id}:{clean["kunci"]}'
    old = await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman == key))
    if old:
        if old.muatan['isian'] != clean or old.muatan['jenis'] != jenis or old.muatan['ident'] != ident:
            raise kirim.PengirimanError('Kunci koreksi sudah dipakai untuk isian berbeda.')
        return dict(ok=True, peristiwa_id=old.id, ulang=True)
    clean, plan = await rancang(db, jenis=jenis, ident=ident, req=req, user=user)
    # Hasil dan penutupan mengunci proses induknya. Kunci yang sama mencegah
    # hasil baru masuk di antara pemeriksaan neraca dan commit koreksi.
    ids = [p['id'] for p in plan['pk_chain'].get('processes', [])]
    if ids:
        list((await db.scalars(select(PolishingProcess).where(PolishingProcess.id.in_(ids))
            .order_by(PolishingProcess.id).with_for_update().execution_options(populate_existing=True))).all())
    from app.penggilingan.gudang2.polishing import kunci_silo
    for sid in plan['pk_chain'].get('silos', []):
        await kunci_silo(db, sid)
        await db.get(Silo, sid, with_for_update=True, populate_existing=True)
    # Siklus/hasil yang baru muncul selama menunggu kunci akan mengubah
    # tanda tangan. Rancangan itu ditolak sebelum ada baris yang diubah.
    clean, plan = await rancang(db, jenis=jenis, ident=ident, req=req, user=user)
    if req.get('konfirmasi') is not True or not hmac.compare_digest(req.get('pemeriksaan', ''), tanda(jenis, ident, user, clean, plan)):
        raise kirim.PengirimanError('Data atau rancangan berubah. Periksa dampak terbaru dan konfirmasikan sebelum menyimpan.')
    try:
        event = await buku.catat(db, jenis=JENIS, pelaku_id=user.id, kunci_kiriman=key,
            muatan=dict(jenis=jenis, ident=ident, isian=clean, rancangan=plan,
                        request={'reason': clean['alasan']}, pk_chain=plan['pk_chain']), terapkan=False)
        if plan['pk_chain']:
            await rantai.terapkan(db, event=event, user=user, aksi=JENIS)
        await _terapkan_baris(db, event, user)
        from app.penggilingan.gudang2.service import hitung_stok_silo
        for sid in plan['pk_chain'].get('silos', []):
            silo = await db.get(Silo, sid)
            saldo = D(str(await hitung_stok_silo(db, sid)))
            if saldo < 0 or silo.kapasitas_ton is not None and saldo > D(str(silo.kapasitas_ton)) * 1000:
                raise kirim.PengirimanError('Saldo atau kapasitas silo tidak mencukupi koreksi. Tidak ada perubahan disimpan.')
        await db.commit()
        return dict(ok=True, peristiwa_id=event.id, ulang=False)
    except Exception:
        await db.rollback()
        raise
