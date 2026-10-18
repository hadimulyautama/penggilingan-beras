"""Contoh keadaan layar, tambahan atas data yang ada; khusus MODE_UJI.

Dipakai atas permintaan pemilik 17 Oktober 2026 untuk meninjau seluruh alur.
Tidak mereset basis data, tidak membuat akun, dan tidak menjalankan scheduler
atau menghubungi layanan luar. Catatan pekerjaan dibuat layanan domain yang
sama dengan aplikasi; hanya master contoh dan tiket lintas-app yang disemai.

Laporan kemajuan tersimpan di setelan_pabrik supaya pengulangan yang selesai
normal tidak menggandakan data. Jangan menghapus kunci itu sebelum data contoh
yang bersangkutan ikut dibersihkan. Semua referensi tersedia dalam laporannya.

    MODE_UJI=true PYTHONPATH=. python scripts/isi_tampilan_uji.py --terapkan
Tanpa --terapkan hanya menampilkan inventaris, tanpa menulis apa pun.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import hashlib
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from sqlalchemy import select, text

from app.config import settings
from app.database import SessionLocal, engine, now_local
from app.models import (Dryer, Pelanggan, Silo, Supplier, User, Warehouse,
                        SetelanPabrik, RiceQualityStandard)
from hmu_identitas.peran import super_saja
from app.penggilingan.gudang1.services import purchase, drying, silo, milling, qc_gabah, tumpukan, jeda, gabah_kering
from app.penggilingan.gudang2 import service as g2, polishing
from app.penggilingan.inventory import packaging, finished_goods
from app.services import barang_keluar as bk, permintaan_pk as pk, transfer, jasa

KUNCI = 'uji_tampilan_20261017_v1'
AWALAN = '(UJI TAMPILAN) '
TIKET = 'TRX-UJI-VIS-'


def waktu(hari=0, jam_lalu=10):
    saat = now_local() - timedelta(days=hari, hours=jam_lalu)
    return {'tanggal': saat.date(), 'jam': saat.timetz()}


def ringkas(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: ringkas(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [ringkas(x) for x in obj]
    if dataclasses.is_dataclass(obj):
        return {f.name: ringkas(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if hasattr(obj, '__table__'):
        return {k: ringkas(v) for k, v in obj.__dict__.items() if k in {
            'id', 'kode', 'kode_batch', 'kode_lot', 'kode_proses', 'jasa_id',
            'product_sku_id', 'rice_quality_standard_id', 'status', 'status_batch'}}
    return str(obj)


class Pengisi:
    def __init__(self, pelaku_id, state):
        self.pelaku_id, self.state = pelaku_id, state

    async def simpan(self):
        async with SessionLocal() as db:
            rec = await db.get(SetelanPabrik, KUNCI)
            if rec is None:
                rec = SetelanPabrik(kunci=KUNCI, nilai='{}', diubah_oleh=self.pelaku_id)
                db.add(rec)
            rec.nilai = json.dumps(self.state, ensure_ascii=False)
            await db.commit()

    async def langkah(self, key, fungsi, **kw):
        if key in self.state['langkah']:
            return self.state['langkah'][key]
        async with SessionLocal() as db:
            user = await db.get(User, self.pelaku_id)
            result = await fungsi(db, user=user, **kw)
            await db.commit()
            result = ringkas(result)
        self.state['langkah'][key] = result
        await self.simpan()
        print('OK', key, flush=True)
        return result

    async def master(self):
        async with SessionLocal() as db:
            wh = {w.kode_fungsi: w.id for w in (await db.scalars(select(Warehouse))).all()}
            if not all(x in wh for x in ('g1', 'g2')):
                raise ValueError('Gudang 1 dan 2 harus sudah tersedia.')
            data = {'pemasok': [], 'pelanggan': [], 'silo': {}, 'dryer': {}}
            for model, field, key, names in (
                (Supplier, 'nama_supplier', 'pemasok', ['Bu Sri', 'UD Sumber Makmur', 'Kelompok Tani Sumber Rejeki Desa Karanganyar']),
                (Pelanggan, 'nama_pelanggan', 'pelanggan', ['Toko Maju', 'PT Beras Sejahtera Nusantara Cabang Distribusi Jawa Tengah', 'Pak Budi Jasa'])):
                for name in names:
                    rec = await db.scalar(select(model).where(getattr(model, field) == AWALAN + name))
                    if rec is None:
                        rec = model(**{field: AWALAN + name}, status='aktif')
                        db.add(rec); await db.flush()
                    data[key].append(rec.id)
            for gudang, letters in [('g1', 'ABC'), ('g2', 'ABCJ')]:
                for letter in letters:
                    name = 'Silo UJI-' + letter
                    rec = await db.scalar(select(Silo).where(Silo.warehouse_id == wh[gudang], Silo.nama_silo == name))
                    if rec is None:
                        rec = Silo(warehouse_id=wh[gudang], nama_silo=name, aktif=True,
                                   jenis_isi='gabah' if gudang == 'g1' else 'campuran',
                                   kapasitas_ton=35 if gudang == 'g1' else None,
                                   komoditas_diizinkan=['gabah_kering'] if gudang == 'g1' else ['pk', 'beras_putih', 'broken', 'menir', 'reject'])
                        db.add(rec); await db.flush()
                    data['silo'][gudang + letter] = rec.id
            for letter in 'ABC':
                name = '(UJI) Pengering ' + letter
                rec = await db.scalar(select(Dryer).where(Dryer.warehouse_id == wh['g1'], Dryer.nama == name))
                if rec is None:
                    rec = Dryer(warehouse_id=wh['g1'], nama=name, kapasitas_kg=30000, status='aktif')
                    db.add(rec); await db.flush()
                data['dryer'][letter] = rec.id
            await db.commit()
        self.state['master'] = data
        await self.simpan()
        return data

    async def tiket(self, key, jenis='GABAH_KERING', kg=10000, hari=0,
                    tahap='selesai', pelanggan=None, supplier=0, nota=None,
                    jasa_barang=False, plate=None, transaksi='AKTIF', **extra):
        async def buat(db, user):
            kode = TIKET + key.upper()[:13] + '-' + hashlib.sha256(key.encode()).hexdigest()[:6]
            ada = await db.scalar(text('SELECT id FROM timbangan_transaksi WHERE kode=:k'), {'k': kode})
            if ada:
                return {'id': ada, 'kode': kode}
            arah = ('RETUR_MASUK' if jenis == 'RETUR_PELANGGAN' else
                    'KELUAR' if jenis in {'PENGIRIMAN', 'BEKATUL', 'BROKEN', 'MENIR', 'REJECT', 'BERAS'} else 'MASUK')
            lengkap = tahap == 'selesai'
            saat = now_local() - timedelta(days=hari, hours=12)
            tara = 4200
            kolom = dict(kode=kode, tanggal=saat.date(), arah=arah, jenis_kode=jenis,
                         nomor_polisi=plate or f'AD {8000 + len(self.state["langkah"])} UJ',
                         nama_sopir='Sopir contoh ' + key,
                         supplier_id=self.state['master']['pemasok'][supplier] if arah == 'MASUK' and not jasa_barang else None,
                         pelanggan_id=pelanggan, pihak_nama=None,
                         timbang1_kg=tara if arah == 'KELUAR' else tara + kg,
                         timbang2_kg=(tara + kg if arah == 'KELUAR' else tara) if lengkap else None,
                         netto_timbangan_kg=kg if lengkap else None,
                         berat_barang_kg=kg if lengkap else None,
                         berat_acuan_kg=nota or 0,
                         berat_bermuatan_kg=tara+kg if lengkap else None, berat_kosong_kg=tara if lengkap else None,
                         status_kontrol='NORMAL', status_tiket='SELESAI' if lengkap else 'TERBUKA',
                         status_transaksi=transaksi, jasa=jasa_barang,
                         timbang1_waktu=saat, timbang2_waktu=saat + timedelta(minutes=45) if lengkap else None,
                         catatan=AWALAN + key)
            kolom.update(extra)
            sql = 'INSERT INTO timbangan_transaksi (' + ','.join(kolom) + ') VALUES (' + ','.join(':' + k for k in kolom) + ') RETURNING id'
            tid = await db.scalar(text(sql), kolom)
            return {'id': tid, 'kode': kode}
        return await self.langkah('tiket:' + key, buat)

    async def gabah(self, key, *, basah=False, kg=10000, hari=0, tahap='selesai', jasa_barang=False, nota=None, qc=2, **extra):
        pid = self.state['master']['pelanggan'][2] if jasa_barang else None
        t = await self.tiket(key, 'GABAH_BASAH' if basah else 'GABAH_KERING', kg, hari,
                             tahap, pelanggan=pid, nota=nota, jasa_barang=jasa_barang, **extra)
        r = await self.langkah(key + ':masuk', purchase.create_purchase_batch_dari_timbang,
                              timbangan_transaksi_id=t['id'], kondisi_gabah='basah' if basah else 'kering',
                              kadar_air_awal_persen=25 if basah else 14)
        b = r['batch']
        for i in range(qc):
            await self.langkah(key + f':qc:{i}', qc_gabah.catat_qc_gabah,
                              kode_batch=b['kode_batch'], kadar_air_1=(25 if basah else 14) - i*.2,
                              kadar_air_2=(24.8 if basah else 13.8) - i*.2,
                              biji_hijau='sedikit', densiti='padat',
                              lamur=(i == 0) if basah else None,
                              jumlah_sak_lamur=(2 if i == 0 else 0) if basah else None)
        return b

    async def keringkan(self, key, *, selesai=True, pendinginan=True, pindah=True, hari=0):
        b = await self.gabah(key, basah=True, hari=hari)
        await self.langkah(key + ':dryer', drying.masuk_dryer, kode_batch_list=[b['kode_batch']], dryer_id=self.state['master']['dryer']['A'])
        r = await self.langkah(key + ':mulai', drying.start_drying, dryer_id=self.state['master']['dryer']['A'], target_kadar_air=14, mode_dryer='15T', **waktu(hari,10))
        kode = r['lot']['kode_lot']
        for i, air in enumerate([24, 20.5, 14]):
            await self.langkah(key + f':air:{i}', drying.log_moisture, kode_lot=kode, indikator=air, tes_manual=air+.2, **waktu(hari,9-i))
        if selesai:
            await self.langkah(key + ':selesai', drying.finish_drying, kode_lot=kode, kadar_air_akhir=14, **waktu(hari,6))
            await self.langkah(key + ':dingin-log', drying.log_cooling, kode_lot=kode, catatan=AWALAN + 'Pembalikan gabah saat pendinginan', **waktu(hari,5.5))
            if pendinginan:
                await self.langkah(key + ':dingin-selesai', drying.finish_cooling, kode_lot=kode, **waktu(hari,5))
                if pindah:
                    await self.langkah(key + ':silo', silo.masuk_silo, nama_silo='UJI-A', kode_lot=kode, kode_batch=None, **waktu(hari,4.5))
        return r['lot']

    async def giling(self, key, *, kg=10000, hari=0, jasa_barang=False, verif=True, sumber=None):
        if sumber is None:
            b = await self.gabah(key, kg=kg, hari=hari, jasa_barang=jasa_barang)
            await self.langkah(key + ':silo', silo.masuk_silo, nama_silo='UJI-A', kode_lot=None, kode_batch=b['kode_batch'], **waktu(hari,11))
        r = await self.langkah(key + ':giling', milling.start_milling, nama_silo='UJI-A', **waktu(hari,10))
        kode = r['proc']['kode_proses']
        for i, hasil in enumerate([kg*.3, kg*.72]):
            await self.langkah(key + f':hasil:{i}', milling.log_progress, kode_proses=kode, berat_kumulatif=hasil, **waktu(hari,9-i))
            await self.langkah(key + f':qc-giling:{i}', milling.log_qc_milling, kode_proses=kode, kadar_air=14-i*.2, broken=22-i, susut=1.5, kondisi='normal',
                              butir_kuning='sedikit' if i == 0 else 'bersih',
                              gabah='sedikit', merang='bersih', catatan_lab=AWALAN + 'QC hasil giling ' + str(i+1))
        await self.langkah(key + ':silo-diperiksa-kosong', milling.tutup_silo_giling, kode_proses=kode, nama_silo='UJI-A', sisa_kg=0, **waktu(hari,7.1))
        await self.langkah(key + ':giling-selesai', milling.finish_milling, kode_proses=kode, berat_akhir=kg*.72, **waktu(hari,7))
        if verif:
            await self.langkah(key + ':verifikasi', milling.verify_milling_output, kode_proses=kode, berat_output=kg*.72)
        return r['proc']

    async def pk_luar(self, key, *, tujuan=None, kg=15000, hari=0, tahap='selesai', jenis_pk='ks', qc=True):
        t = await self.tiket(key, 'BERAS_PK', kg, hari, tahap)
        r = await self.langkah(key + ':pk-masuk', g2.create_pk_purchase_dari_timbang,
                              timbangan_transaksi_id=t['id'], jenis_pk=jenis_pk, kadar_air=14)
        kode = r['batch']['kode_batch']
        for i in range(2 if qc else 0):
            await self.langkah(key + f':qc-pk:{i}', g2.log_pk_qc, kode=kode, kadar_air=14-i*.2,
                              broken=20-i, penyusutan_persen=2, butir_kuning='sedikit',
                              gabah='sedikit', merang='bersih', catatan_lab=AWALAN + 'QC putaran ' + str(i+1))
        if tujuan:
            intake = await self.langkah(key + ':terima', g2.masukkan_pk_luar, kode=kode, tujuan='ditumpuk', **waktu(hari,11))
            if tujuan != 'ditumpuk':
                await self.langkah(key + ':pindah-silo', g2.pindah_tumpukan_ke_silo,
                                  intake_id=intake['intake']['id'], nama_silo=tujuan, berat=kg,
                                  **waktu(hari,10.5))
        return r['batch']

    async def sosoh(self, key, *, kg=15000, selesai=True, jasa_barang=False):
        letter = 'UJI-J' if jasa_barang else 'UJI-A'
        if not jasa_barang:
            await self.pk_luar(key, tujuan=letter, kg=kg, hari=2 if selesai else 0)
        hari = 2 if selesai and not jasa_barang else 0
        r = await self.langkah(key + ':sosoh', polishing.mulai_penyosohan, nama_silos=[letter], **(waktu(hari,10) if not jasa_barang else {}))
        kode = r['proc']['kode_proses']
        for jenis, hasil in [('premium', .32), ('medium', .22), ('medsuper', .12), ('sayur', .06), ('broken', .08), ('menir', .03), ('reject', .02), ('bekatul', .1)]:
            await self.langkah(key + ':output:' + jenis, polishing.catat_output,
                              kode=kode, jenis=jenis, berat_kg=kg*hasil, spek='(UJI) Spek ' + ('A' if jenis in {'premium','medium'} else 'B'), **(waktu(hari,8) if not jasa_barang else {}))
        if selesai:
            await self.langkah(key + ':sosoh-selesai', polishing.selesai_penyosohan, kode=kode, nama_silo=letter, sisa_kg=0, **(waktu(hari,6) if not jasa_barang else {}))
        return r['proc']

    async def isi(self):
        m = await self.master()
        # Riwayat lengkap pengeringan → giling → transfer → penyosohan.
        lot = await self.keringkan('riwayat-kering', hari=12)
        mill = await self.giling('riwayat-kering-giling', sumber=lot, hari=11)
        await self.langkah('transfer-langsung', transfer.create_internal_transfer,
                          kode_proses=mill['kode_proses'], lokasi_tujuan='ditumpuk', berat=1500)
        # Setiap keadaan rantai permintaan mendapat lot yang berbeda.
        for i, status in enumerate(['diminta', 'disetujui', 'dikirim', 'selesai', 'ditolak', 'gugur']):
            key = 'permintaan-' + status
            p = await self.giling(key, hari=10-i)
            r = await self.langkah(key + ':minta', pk.minta, kode_proses=p['kode_proses'], berat=2000)
            if status in {'disetujui', 'dikirim', 'selesai'}:
                await self.langkah(key + ':acc', pk.setujui, permintaan_id=r['id'], tujuan='ditumpuk', berat=1800)
            if status in {'dikirim', 'selesai'}:
                await self.langkah(key + ':kirim', pk.kirim, permintaan_id=r['id'], berat=1700)
            if status == 'selesai':
                await self.langkah(key + ':tutup', pk.tutup_admin, permintaan_id=r['id'], berat_final=1700)
            if status == 'ditolak':
                await self.langkah(key + ':tolak', pk.tolak, permintaan_id=r['id'], sebab=AWALAN + 'Stok Gudang 2 masih cukup')
            if status == 'gugur':
                await self.langkah(key + ':habiskan', transfer.create_internal_transfer, kode_proses=p['kode_proses'], lokasi_tujuan='ditumpuk', berat=7200)
                async def gugur(db, user): return await pk.gugurkan_yang_habis(db)
                await self.langkah(key + ':gugur', gugur)
        await self.giling('hasil-belum-verifikasi', hari=4, verif=False)
        # Barang jasa melewati rantai yang sama, dengan pemilik tetap melekat.
        p = await self.giling('jasa-lengkap', jasa_barang=True, hari=3)
        await self.langkah('jasa-transfer', transfer.create_internal_transfer, kode_proses=p['kode_proses'], lokasi_tujuan='UJI-J', berat=7200)
        jasa_proc = await self.sosoh('jasa-sosoh', kg=7200, jasa_barang=True)
        normal = await self.sosoh('stok-produk')
        # Variasi mutu, merek, ukuran dan hasil samping.
        packs = [('premium','laminasi',5,200,'Imbiss'), ('premium','laminasi',25,80,'Imbiss'),
                 ('medium','biasa',25,80,'LosPulen'), ('medium','putih',50,20,'Polos'),
                 ('medsuper','laminasi',10,100,'Pulenesia'), ('sayur','biasa',50,12,'Polos'),
                 ('broken','polos',25,20,None), ('menir','putih',50,5,None),
                 ('reject','bekas',50,4,None), ('bekatul','bekas',40,10,None)]
        self.state['produk'] = []
        for i, (grade, mat, size, count, brand) in enumerate(packs):
            kategori = 'beras_putih' if grade in {'premium','medium','medsuper','sayur'} else grade
            await self.langkah(f'karung:{i}', packaging.beli_kemasan, material_kode=mat, ukuran=size, jumlah=600, brand_nama=brand or ('Polos' if mat in packaging._KARUNG_BERMERK else None))
            await self.langkah(f'packing:{i}', finished_goods.catat_packing, kode_pol=normal['kode_proses'], kategori=kategori,
                              grade=grade if kategori=='beras_putih' else None, brand_nama=brand, material_kode=mat, ukuran=size, jumlah_karung=count)
            async with SessionLocal() as db:
                sku = await packaging.find_or_create_sku(db, kategori=kategori, material_kode=mat, ukuran=size, brand_nama=brand)
                std = await packaging.get_standard(db, grade) if kategori=='beras_putih' else None
                self.state['produk'].append(dict(sku_id=sku.id, std_id=std.id if std else None))
        await self.simpan()
        await self.langkah('bekatul-curah', finished_goods.catat_bekatul, kode_pol=normal['kode_proses'], berat_kg=500)
        await self.langkah('broken-curah', finished_goods.catat_broken, kode_pol=normal['kode_proses'], berat_kg=500)
        await self.langkah('jasa-karung', packaging.beli_kemasan, material_kode='biasa', ukuran=25, jumlah=200, brand_nama='LosPulen')
        await self.langkah('karung-milik-jasa', packaging.pindah_kepemilikan_karung,
                          material_kode='biasa', ukuran=25, brand_nama='LosPulen',
                          pelanggan_id=m['pelanggan'][2], jumlah_lembar=100)
        await self.langkah('jasa-packing', finished_goods.catat_packing, kode_pol=jasa_proc['kode_proses'], kategori='beras_putih', grade='medium', brand_nama='LosPulen', material_kode='biasa', ukuran=25, jumlah_karung=40)
        # Semua tahap pengiriman dan beberapa bentuk muatan.
        for i, status in enumerate(['perintah', 'sebagian', 'dimuat', 'selesai', 'tanpa-tiket', 'selisih', 'batal', 'curah', 'campuran', 'armada-belum-datang', 'jasa']):
            key = 'keluar-' + status
            produk = self.state['produk'][i % 3]
            baris = [bk.BarisPerintah(tipe='finished_goods', jumlah_karung=8, **produk)]
            if status == 'tanpa-tiket': baris = [bk.BarisPerintah(tipe='finished_goods', jumlah_karung=2, **self.state['produk'][0])]
            if status == 'curah': baris = [bk.BarisPerintah(tipe='byproduct_curah', jenis='bekatul', berat_kg=100)]
            if status == 'campuran': baris += [bk.BarisPerintah(tipe='finished_goods', jumlah_karung=2, **self.state['produk'][6])]
            jid = jasa_proc.get('jasa_id') if status == 'jasa' else None
            if jid: baris = [bk.BarisPerintah(tipe='finished_goods', jumlah_karung=10, **self.state['produk'][2])]
            r = await self.langkah(key + ':perintah', bk.buat_perintah, baris=baris,
                                  pelanggan_id=m['pelanggan'][2 if jid else i % 2], jasa_id=jid,
                                  no_polisi=None if status=='armada-belum-datang' else f'AD {9100+i} UJ',
                                  catatan=AWALAN + 'Skenario ' + status)
            rid = r['rec']['id']
            if status == 'sebagian':
                await self.langkah(key + ':sebagian', bk.catat_muatan, item_id=r['baris'][0]['id'], jumlah_karung=5)
            elif status == 'batal':
                await self.langkah(key + ':batal', bk.batalkan, rec_id=rid, sebab=AWALAN + 'Pelanggan menunda pengambilan')
            elif status not in {'perintah','armada-belum-datang','jasa'}:
                r = await self.langkah(key + ':muat', bk.muat_semua, rec_id=rid)
                if status in {'selesai','tanpa-tiket','selisih'}:
                    tid = None
                    if status != 'tanpa-tiket':
                        async with SessionLocal() as db:
                            from app.models import OutgoingItem
                            its=(await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==rid))).all()
                            berat=sum(float(it.berat_kg or 0) for it in its)
                        t = await self.tiket(key, 'PENGIRIMAN', berat + (250 if status=='selisih' else 0), pelanggan=None, plate=f'AD {9100+i} UJ')
                        tid = t['id']
                    await self.langkah(key + ':verifikasi', bk.verifikasi, rec_id=rid, timbangan_transaksi_id=tid,
                                      sebab_selisih=AWALAN + 'Penambahan muatan setelah catatan awal' if status=='selisih' else None)
        await self.retur()
        await self.tambahan()
        # Antrean bahan, sumber berat, QC belum ada/sebagian/lengkap.
        for key, kw in [('belum-qc',dict(qc=0)), ('qc-lengkap',dict(qc=5)),
                        ('belum-timbang-kosong',dict(tahap='terbuka',qc=0)),
                        ('nota-selisih-wajar',dict(nota=10010)), ('nota-selisih-besar',dict(nota=10500))]:
            await self.gabah(key, **kw)
        for key, basah in [('tumpukan-basah',True), ('tumpukan-kering',False)]:
            b=await self.gabah(key, basah=basah)
            await self.langkah(key + ':tumpuk', tumpukan.masuk_tumpukan, kode_batch=b['kode_batch'])
        # Pendinginan disiapkan sebelum dryer A dipakai proses yang masih hidup.
        await self.keringkan('pendinginan', pendinginan=False, pindah=False)
        # Dua mesin lain menunjukkan proses berjalan dan jeda.
        for letter, pause in [('B',False),('C',True)]:
            key='kering-berjalan-'+letter
            b=await self.gabah(key,basah=True)
            await self.langkah(key+':dryer',drying.masuk_dryer,kode_batch_list=[b['kode_batch']],dryer_id=m['dryer'][letter])
            r=await self.langkah(key+':mulai',drying.start_drying,dryer_id=m['dryer'][letter],target_kadar_air=14,mode_dryer='15T')
            await self.langkah(key+':air',drying.log_moisture,kode_lot=r['lot']['kode_lot'],indikator=21,tes_manual=21.2)
            if pause: await self.langkah(key+':jeda',jeda.hentikan,jenis='pengeringan',kode=r['lot']['kode_lot'],sebab='Lainnya',sebab_lain='(UJI) Perawatan burner')
        for letter,pause in [('B',False),('C',True)]:
            key='giling-berjalan-'+letter
            b=await self.gabah(key)
            await self.langkah(key+':silo',silo.masuk_silo,nama_silo='UJI-'+letter,kode_lot=None,kode_batch=b['kode_batch'])
            r=await self.langkah(key+':mulai',milling.start_milling,nama_silo='UJI-'+letter)
            await self.langkah(key+':hasil',milling.log_progress,kode_proses=r['proc']['kode_proses'],berat_kumulatif=2800)
            if pause: await self.langkah(key+':jeda',jeda.hentikan,jenis='giling',kode=r['proc']['kode_proses'],sebab='Lainnya',sebab_lain='(UJI) Pemeriksaan mesin')
        for letter,pause in [('B',False),('C',True)]:
            key='sosoh-berjalan-'+letter
            await self.pk_luar(key,tujuan='UJI-'+letter)
            r=await self.langkah(key+':mulai',polishing.mulai_penyosohan,nama_silos=['UJI-'+letter])
            await self.langkah(key+':hasil',polishing.catat_output,kode=r['proc']['kode_proses'],jenis='medium',berat_kg=3000,spek='(UJI) Medium')
            if pause: await self.langkah(key+':jeda',jeda.hentikan,jenis='penyosohan',kode=r['proc']['kode_proses'],sebab='Lainnya',sebab_lain='(UJI) Penggantian ayakan')
        await self.pk_luar('pk-tumpukan',tujuan='ditumpuk')
        await self.pk_luar('pk-belum-bobot',tahap='terbuka')
        for jenis in ['kl','semi_ks','campuran']:
            await self.pk_luar('pk-'+jenis,tujuan='ditumpuk',jenis_pk=jenis,qc=jenis!='kl')
        t=await self.tiket('pk-ditolak','BERAS_PK',8000)
        await self.langkah('pk-ditolak',g2.create_pk_rejection_dari_timbang,timbangan_transaksi_id=t['id'],alasan=AWALAN+'Bau apek dan banyak butir kuning')
        # Tiket yang belum dibukukan, serta batal, juga terlihat di Pos Timbang.
        for jenis in ['GABAH_BASAH','GABAH_KERING','BERAS_PK','PENGIRIMAN']:
            await self.tiket('antrean-'+jenis,jenis,8500,tahap='terbuka')
        await self.tiket('tiket-batal','GABAH_KERING',5000,transaksi='VOID')
        self.state['selesai']=now_local().isoformat()
        await self.simpan()
        return self.state

    async def tambahan(self):
        m=self.state['master']
        # Jalur masuk barang jadi memakai aksi aplikasi yang sebenarnya.
        from app.web.api import act_catat_produk_timbang_masuk, CatatProdukTimbangMasukReq
        for jenis in ['BERAS_MASUK','BROKEN_MASUK']:
            t=await self.tiket('beli-'+jenis,jenis,5000)
            async def terima(db,user):
                return await act_catat_produk_timbang_masuk(CatatProdukTimbangMasukReq(timbangan_transaksi_id=t['id']),user=user)
            await self.langkah('beli-'+jenis+':stok',terima)
        # Jasa selesai: gabah kering diambil utuh oleh pemiliknya.
        b=await self.gabah('jasa-diambil-utuh',kg=1000,jasa_barang=True,qc=0)
        r=await self.langkah('jasa-diambil:silo',silo.masuk_silo,nama_silo='UJI-A',kode_lot=None,kode_batch=b['kode_batch'])
        async with SessionLocal() as db:
            from app.models import SiloStorage
            sid=await db.scalar(select(SiloStorage.id).where(SiloStorage.purchase_batch_id==b['id'],SiloStorage.status=='terisi'))
        r=await self.langkah('jasa-diambil:kemas',gabah_kering.keluarkan_untuk_kemasan,silo_storage_id=sid,berat_kg=1000,jumlah_karung=20)
        await self.langkah('jasa-diambil:silo-kosong',silo.keluar_silo,nama_silo='UJI-A')
        r=await self.langkah('jasa-diambil:perintah',bk.buat_perintah,
                            baris=[bk.BarisPerintah(tipe='gabah_langsung',gabah_kering_lot_id=r['lot']['id'],berat_kg=1000)],
                            pelanggan_id=m['pelanggan'][2],jasa_id=b['jasa_id'],no_polisi='AD 9291 UJ',catatan=AWALAN+'Pengambilan utuh dan penyelesaian jasa')
        await self.langkah('jasa-diambil:muat',bk.muat_semua,rec_id=r['rec']['id'])
        await self.langkah('jasa-diambil:verifikasi',bk.verifikasi,rec_id=r['rec']['id'])
        await self.langkah('jasa-diambil:tutup',jasa.tutup_pesanan,jasa_id=b['jasa_id'])
        # Pembatalan berjalan lewat mekanisme audit dan peristiwa lawan.
        b=await self.gabah('jasa-pencatatan-keliru',kg=1000,jasa_barang=True,qc=0)
        async def balik(db,user):
            from app.models import ActivityLog
            from app.services.undo import undo_last
            lid=await db.scalar(select(ActivityLog.id).where(ActivityLog.table_name=='purchase_batches',ActivityLog.record_id==b['id'],ActivityLog.action=='INSERT').order_by(ActivityLog.id.desc()))
            return await undo_last(db,actor=user,cakupan=None,log_id=lid)
        await self.langkah('jasa-pencatatan:batalkan',balik)
        # Silo dengan beberapa asal dan sebagian gabah sudah dikemas.
        for i in range(2):
            b=await self.gabah('silo-campuran-'+str(i),kg=3000,supplier=i)
            await self.langkah(f'silo-campuran:{i}',silo.masuk_silo,nama_silo='UJI-A',kode_lot=None,kode_batch=b['kode_batch'])
        async with SessionLocal() as db:
            from app.models import SiloStorage
            sid=await db.scalar(select(SiloStorage.id).where(SiloStorage.purchase_batch_id==b['id'],SiloStorage.status=='terisi'))
        r=await self.langkah('gabah-kering:kemas',gabah_kering.keluarkan_untuk_kemasan,silo_storage_id=sid,berat_kg=1500,jumlah_karung=30)
        await self.langkah('gabah-kering:perintah',bk.buat_perintah,
                          baris=[bk.BarisPerintah(tipe='gabah_langsung',gabah_kering_lot_id=r['lot']['id'],berat_kg=500)],
                          pelanggan_id=m['pelanggan'][0],no_polisi='AD 9292 UJ',catatan=AWALAN+'Gabah kering dijual langsung')

    async def retur(self):
        from app.web import layar_retur
        from app.web.security import butuh_akun
        app=FastAPI(); app.include_router(layar_retur.router)
        async with SessionLocal() as db: actor=await db.get(User,self.pelaku_id)
        app.dependency_overrides[butuh_akun]=lambda: SimpleNamespace(user=actor)
        for name, tahap, aksi, delta in [('belum-rincian','terbuka',None,0),('rincian-disimpan','terbuka','rincian',0),('menunggu-verifikasi','selesai',None,0),('diterima','selesai','terima',0),('selisih','selesai','terima',25)]:
            key='retur-'+name
            t=await self.tiket(key,'RETUR_PELANGGAN',250+delta,tahap=tahap,pelanggan=self.state['master']['pelanggan'][0])
            if not aksi: continue
            async def terima(db,user):
                data=dict(timbangan_transaksi_id=str(t['id']),sku_id=str(self.state['produk'][2]['sku_id']),quality_id=str(self.state['produk'][2]['std_id']),jumlah_karung='10',catatan_item=AWALAN+'Kemasan sobek saat pengiriman',catatan=AWALAN+name,alasan_selisih=AWALAN+'Sebagian karung basah, ditimbang terpisah' if delta else '',aksi=aksi)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
                    r=await c.post('/retur/terima',data=data)
                from urllib.parse import unquote
                location=unquote(r.headers.get('location',''))
                if r.status_code!=303 or 'gagal=' in location: raise ValueError(location or r.text[:300])
                return {'tiket_id':t['id'],'aksi':aksi}
            await self.langkah(key+':'+aksi,terima)


async def periksa_halaman(simpan_di=None):
    """Render data melalui rute, autentikasi dan izin aplikasi sebenarnya.

    ASGI tanpa lifespan tidak menyalakan scheduler atau integrasi luar.
    Token dipakai di memori proses ini saja dan tidak pernah dikembalikan.
    """
    from pathlib import Path
    from app.models import ProduksiAkun, OutgoingRecord, CustomerReturn, MillingProcess, DryingLot, PolishingProcess
    from app.web.security import buat_token, NAMA_COOKIE
    from app.main import app
    async with SessionLocal() as db:
        akun=next(a for a in (await db.scalars(select(ProduksiAkun).where(ProduksiAkun.status=='aktif'))).unique().all() if a.is_super and a.aktif)
        alamat=['/','/aksi','/berjalan','/keputusan','/mutu','/stok','/stok-pk-jasa','/stok-produk',
                '/stok-produk-jasa','/stok-karung','/stok-karung-jasa','/barang-keluar','/retur',
                '/jasa','/jasa?status=selesai','/jasa?status=dibatalkan',
                '/riwayat-pengeringan','/riwayat-giling','/riwayat-transfer','/riwayat-sosoh','/audit','/kabar']
        alamat += ['/riwayat-qc/'+j for j in ['gabah-basah','gabah-kering','pk-luar','pk-hasil-giling','beras-hasil-sosoh']]
        for model,kolom,path in [(OutgoingRecord,OutgoingRecord.id,'/barang-keluar/'),(CustomerReturn,CustomerReturn.id,'/retur/'),
                                 (MillingProcess,MillingProcess.id,'/riwayat-giling/'),(DryingLot,DryingLot.id,'/riwayat-pengeringan/'),
                                 (PolishingProcess,PolishingProcess.id,'/riwayat-sosoh/')]:
            q=select(kolom)
            if model in (MillingProcess,DryingLot,PolishingProcess):
                q=q.where(model.status=='selesai')
            if model is DryingLot:
                q=q.where(DryingLot.waktu_selesai_pendinginan.is_not(None))
            alamat += [path+str(i) for i in (await db.scalars(q.order_by(kolom.desc()).limit(3))).all()]
    hasil={}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji',cookies={NAMA_COOKIE:buat_token(akun)}) as c:
        for path in alamat:
            r=await c.get(path)
            hasil[path]=r.status_code
            if r.status_code!=200: raise ValueError(f'Halaman {path}: HTTP {r.status_code}')
            if simpan_di:
                dest=Path(simpan_di); dest.mkdir(parents=True,exist_ok=True)
                (dest/(path.strip('/').replace('/','_').replace('?','_') or 'beranda')).with_suffix('.html').write_text(r.text)
    return hasil


async def jalankan(terapkan=False):
    if not settings.mode_uji:
        raise ValueError('MODE_UJI harus aktif. Tidak ada data yang ditulis.')
    # Kunci lintas proses mencegah dua pengisi bekerja pada skenario yang sama.
    async with engine.connect() as lock:
        if not await lock.scalar(text('SELECT pg_try_advisory_lock(20261017, 17858)')):
            raise ValueError('Pengisian contoh tampilan lain masih berlangsung.')
        try:
            async with SessionLocal() as db:
                actor=next((u for u in (await db.scalars(select(User).where(User.status=='aktif').order_by(User.id))).all() if super_saja(u.role)),None)
                if actor is None: raise ValueError('Diperlukan akun Super Admin yang sudah ada; skrip tidak membuat akun.')
                saved=await db.get(SetelanPabrik,KUNCI)
                state=json.loads(saved.nilai) if saved else {'mulai':now_local().isoformat(),'langkah':{},'penanda':AWALAN,'awalan_tiket':TIKET}
            print(json.dumps({'mode_uji':True,'langkah_sudah_ada':len(state['langkah']),'sudah_selesai':bool(state.get('selesai'))}))
            if not terapkan: return state
            pengisi=Pengisi(actor.id,state)
            if state.get('selesai'): return state
            return await pengisi.isi()
        finally:
            await lock.execute(text('SELECT pg_advisory_unlock(20261017, 17858)'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--terapkan',action='store_true')
    args=parser.parse_args()
    hasil=asyncio.run(jalankan(args.terapkan))
    print(json.dumps(hasil,ensure_ascii=False,indent=2))
