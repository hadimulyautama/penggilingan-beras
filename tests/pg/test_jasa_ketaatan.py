"""Uji ketaatan JASA: pemilik barang terbawa utuh, dan tak pernah tercampur.

Bentuknya mengikuti `test_bentuk_borongan_sama_dengan_bentuk_tunggal`
(`tests/pg/test_stok_produk.py`) — uji yang membandingkan dua jawaban yang WAJIB
sama, dan pernah menangkap kesalahan nyata. Di sini yang dibandingkan `jasa_id`
sebuah tabel dengan `jasa_id` turunannya di seluruh rantai: gagal bila berbeda
SATU BARIS pun.

Tiga hal yang dijaga, dan ketiganya pernah jadi lubang di rancangan:

  1. **Pemilik terbawa.** Tiket → batch → lot pengeringan → isi silo → lot
     giling → transfer → pemasukan Gudang 2. Satu tautan yang lupa membawa
     `jasa_id` membuat barang pelanggan berubah jadi barang pabrik DI TENGAH
     JALAN, tanpa satu pun galat.
  2. **Campur pemilik DITOLAK** di setiap titik campur — dan ditolak, bukan
     diperingatkan.
  3. **NULL = milik pabrik, dan perilaku hari ini tidak bergeser satu baris
     pun.** Ini yang paling mudah rusak diam-diam: penjaga baru yang terlalu
     rajin akan menolak gabah pabrik yang selama ini sah.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio

#: Kalimat penolakan yang SAMA yang dipakai layanannya — diimpor, bukan disalin.
#:
#: Uji yang menyalin kalimatnya akan tetap lulus saat kalimat di layanan
#: berubah, dan yang lebih buruk: uji yang hanya memeriksa "melempar galat" tetap
#: lulus pada hari penjaga pemiliknya hilang, sebab penolakan LAIN (silo kosong,
#: sedang digiling, kapasitas) mengambil alih tempatnya tanpa seorang pun tahu.
from app.services.jasa import _PESAN_CAMPUR  # noqa: E402

#: Tiket timbang MASUK — sengaja SQL mentah, sama seperti uji tiket lain:
#: `timbangan_transaksi` tak ada di metadata app ini (dimiliki repo timbangan).
_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pelanggan_id,
         jasa_id, jasa, pihak_nama, nomor_polisi, timbang1_kg, timbang1_waktu,
         netto_timbangan_kg, berat_barang_kg, berat_acuan_kg,
         status_tiket, status_transaksi)
    VALUES (:kode, :tanggal, 'MASUK', :jenis, 'DUA_KALI', :supplier_id, :pelanggan_id,
            :jasa_id, :jasa, :pihak, :nopol, 20000, :waktu, :berat, :berat, 0,
            'SELESAI', 'AKTIF')
    RETURNING id
""")


def _sekarang():
    """Waktu berzona — kolom waktu di app ini `timestamptz`."""
    return datetime.now(timezone.utc)


async def _pelanggan(db, nama: str) -> int:
    from app.models import Pelanggan

    p = Pelanggan(nama_pelanggan=nama)
    db.add(p)
    await db.flush()
    return p.id


async def _tiket(db, *, kode, berat, pelanggan_id=None, jasa_id=None,
                 supplier_id=None, jenis="GABAH_KERING", nopol="B 1 UJ",
                 jasa=None, pihak_nama=None):
    """Tiket timbang MASUK. `jasa` bawaannya DITURUNKAN (pelanggan_id atau
    jasa_id terisi) — kaki kedua yang sama dengan `adalah_jasa()` sendiri,
    supaya pemanggil lama yang tak pernah menyebut `jasa` tetap benar.

    Berikan `jasa=True, pelanggan_id=None` terang-terangan untuk menguji
    bentuk LAPANGAN: pelanggan BARU diketik bebas, belum ada baris
    `pelanggan` — lihat `test_pelanggan_baru_ketik_bebas_*` di bawah.
    """
    from app.database import now_local

    if jasa is None:
        jasa = bool(pelanggan_id or jasa_id)
    if pihak_nama is None:
        pihak_nama = None if (pelanggan_id or jasa) else "Pak Uji"
    return (await db.execute(_SQL_TIKET, {
        "kode": kode, "tanggal": now_local().date(), "jenis": jenis,
        "supplier_id": supplier_id, "pelanggan_id": pelanggan_id,
        "jasa_id": jasa_id, "jasa": jasa, "pihak": pihak_nama,
        "nopol": nopol, "berat": berat,
        "waktu": datetime.now(timezone.utc)})).scalar_one()


async def _terima(db, tid, user_id, kondisi="kering"):
    from app.models import User
    from app.penggilingan.gudang1.services.purchase import (
        create_purchase_batch_dari_timbang)

    u = await db.get(User, user_id)
    return await create_purchase_batch_dari_timbang(
        db, user=u, timbangan_transaksi_id=tid, kondisi_gabah=kondisi)


@pytest.fixture
async def admin(pg, pabrik):
    """Satu Admin — jalur PK luar berpagar peran sebelum apa pun diperiksa."""
    from hmu_identitas import peran as P

    from app.models import User

    async with pg() as db:
        u = User(nama="Elfira", role=P.ADMIN, status="aktif",
                 default_warehouse_id=pabrik["g2"])
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


@pytest.fixture
async def pabrik(pg):
    """Dua gudang, dua silo G1, dua silo G2, satu pengering.

    ⚠ Nama gudang BUKAN hiasan: `silo._g1_warehouse_id` mencarinya dengan
    `nama_gudang LIKE 'Gudang 1%'`, dan gudang bernama lain membuat seluruh
    layanan silo menjawab "Data gudang 1 belum ada". Bentuknya disamakan dengan
    fixture `pabrik` di `test_cermin_bertanda.py`.
    """
    from app.models import Dryer, Silo, Warehouse

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add_all([g1, g2])
        await db.flush()
        db.add_all([
            Silo(nama_silo="Silo A", warehouse_id=g1.id, kapasitas_ton=35),
            Silo(nama_silo="Silo B", warehouse_id=g1.id, kapasitas_ton=35),
            Silo(nama_silo="Silo A", warehouse_id=g2.id, kapasitas_ton=30),
            Silo(nama_silo="Silo B", warehouse_id=g2.id, kapasitas_ton=30),
            Dryer(warehouse_id=g1.id, nama="Dryer 1", kapasitas_kg=30_000,
                  status="aktif"),
        ])
        await db.commit()
        return {"g1": g1.id, "g2": g2.id}


# ═══════════════════════ 1 · PEMILIK TERBAWA ═══════════════════════

async def test_pesanan_lahir_saat_tiket_diterima_dan_batch_tanpa_pemasok(
        pg, pemakai):
    """Tiket ber-pelanggan → pesanan BARU + batch ber-`jasa_id`, `supplier_id` NULL.

    Dan tak ada pemasok palsu yang lahir: `find_or_create_supplier` di jalur lama
    akan membuat baris `suppliers` bernama pelanggan, lalu barang yang tak pernah
    dibeli ikut ke skor pemasok, laporan pembelian, dan HPP.
    """
    from app.models import Jasa, Supplier

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        tid = await _tiket(db, kode="JT01", berat=12_000, pelanggan_id=pid)
        await db.commit()
    async with pg() as db:
        r = await _terima(db, tid, pemakai.id)
        assert r.jasa is not None and r.jasa_baru, "pesanan tak lahir"
        assert r.supplier is None, "barang jasa tak boleh punya pemasok"
        assert r.batch.supplier_id is None
        assert r.batch.jasa_id == r.jasa.id
        assert r.jasa.kode.startswith("JAS-")
        assert r.jasa.hasil_ditahan == "sekam,bekatul"
    async with pg() as db:
        pemasok = (await db.execute(select(Supplier))).scalars().all()
        assert [s.nama_supplier for s in pemasok if "Budi" in s.nama_supplier] == [], \
            "pemasok palsu lahir dari nama pelanggan"
        assert len((await db.execute(select(Jasa))).scalars().all()) == 1


async def test_dua_truk_satu_pesanan_bila_tiketnya_menunjuk(pg, pemakai):
    """24 ton dengan truk 12 ton = dua tiket, SATU pesanan.

    Kalau pesanan lahir per tiket, satu pekerjaan terpecah jadi dua — dan
    `pastikan_satu_jasa()` kemudian menolak menggiling keduanya bersama, benar
    menurut aturannya dan salah menurut kenyataannya.
    """
    from app.models import Jasa

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        t1 = await _tiket(db, kode="JT10", berat=12_000, pelanggan_id=pid)
        await db.commit()
    async with pg() as db:
        r1 = await _terima(db, t1, pemakai.id)
        jid = r1.jasa.id
    async with pg() as db:
        t2 = await _tiket(db, kode="JT11", berat=12_000, pelanggan_id=pid,
                          jasa_id=jid, nopol="B 2 UJ")
        await db.commit()
    async with pg() as db:
        r2 = await _terima(db, t2, pemakai.id)
        assert not r2.jasa_baru, "tiket susulan melahirkan pesanan kedua"
        assert r2.jasa.id == jid
        assert r2.batch.jasa_id == jid
    async with pg() as db:
        assert len((await db.execute(select(Jasa))).scalars().all()) == 1


async def test_pemilik_terbawa_sampai_pemasukan_gudang_2(pg, pemakai, pabrik):
    """RANTAI PENUH: batch → silo → giling → transfer → pemasukan G2.

    Dibandingkan satu per satu, bukan di ujungnya saja: tautan yang lupa
    membawa `jasa_id` di tengah rantai akan terbaca sebagai "barang pabrik" di
    seluruh hilirnya, dan pemeriksaan yang hanya melihat ujungnya akan lulus
    pada hari tautan pertama yang rusak.
    """
    from app.models import (InternalTransfer, MillingProcess, PkGudang2Intake,
                            PurchaseBatch, SiloStorage, User)
    from app.penggilingan.gudang1.services.milling import (finish_milling,
                                                           start_milling)
    from app.penggilingan.gudang1.services.silo import masuk_silo

    async with pg() as db:
        pid = await _pelanggan(db, "Bu Sri")
        tid = await _tiket(db, kode="JT20", berat=10_000, pelanggan_id=pid)
        await db.commit()
        nama_silo = "A"

    async with pg() as db:
        r = await _terima(db, tid, pemakai.id)
        jid, kode_batch = r.jasa.id, r.batch.kode_batch

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo=nama_silo, kode_lot=None,
                         kode_batch=kode_batch)
    async with pg() as db:
        baris = (await db.execute(select(SiloStorage))).scalars().all()
        assert [b.jasa_id for b in baris] == [jid], "isi silo kehilangan pemiliknya"

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        hasil = await start_milling(db, user=u, nama_silo=nama_silo)
        kode_proses = hasil.proc.kode_proses
    async with pg() as db:
        proc = (await db.execute(
            select(MillingProcess).where(
                MillingProcess.kode_proses == kode_proses))).scalars().one()
        assert proc.jasa_id == jid, "lot giling kehilangan pemiliknya"

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await finish_milling(db, user=u, kode_proses=kode_proses, berat_akhir=7_000)

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        from app.services.transfer import create_internal_transfer
        await create_internal_transfer(db, user=u, kode_proses=kode_proses,
                                       lokasi_tujuan="ditumpuk", berat=3_000)
    async with pg() as db:
        trf = (await db.execute(select(InternalTransfer))).scalars().all()
        assert [t.jasa_id for t in trf] == [jid], "transfer kehilangan pemiliknya"
        masuk = (await db.execute(select(PkGudang2Intake))).scalars().all()
        assert [m.jasa_id for m in masuk] == [jid], \
            "pemasukan Gudang 2 kehilangan pemiliknya"

    # Dan batch-nya sendiri tetap tanpa pemasok dari awal sampai akhir.
    async with pg() as db:
        b = (await db.execute(select(PurchaseBatch))).scalars().one()
        assert (b.supplier_id, b.jasa_id) == (None, jid)


# ═══════════════════ 2 · CAMPUR PEMILIK DITOLAK ═══════════════════

async def test_silo_menolak_dua_pemilik(pg, pemakai, pemasok, pabrik):
    """Gabah pabrik + gabah jasa dalam satu silo → DITOLAK, bukan diperingatkan.

    Campuran NULL dengan non-NULL ditolak sekeras dua pesanan berbeda: keluaran
    lot campuran tak bisa dibagi, dan rendemen yang dipakai menagih jadi
    rendemen atas bahan yang sebagian bukan milik penagihnya.
    """
    from app.models import User
    from app.penggilingan.gudang1.services.silo import SiloError, masuk_silo

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        t_jasa = await _tiket(db, kode="JT30", berat=8_000, pelanggan_id=pid)
        t_beli = await _tiket(db, kode="JT31", berat=8_000,
                              supplier_id=pemasok.id, nopol="B 9 UJ")
        await db.commit()
        nama_silo = "A"
    async with pg() as db:
        r1 = await _terima(db, t_jasa, pemakai.id)
        kode_jasa = r1.batch.kode_batch
    async with pg() as db:
        r2 = await _terima(db, t_beli, pemakai.id)
        kode_beli = r2.batch.kode_batch
        assert r2.batch.jasa_id is None and r2.batch.supplier_id is not None

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo=nama_silo, kode_lot=None,
                         kode_batch=kode_jasa)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(SiloError) as e:
            await masuk_silo(db, user=u, nama_silo=nama_silo, kode_lot=None,
                             kode_batch=kode_beli)
        # Penolakannya MENYEBUT pemiliknya: operator yang berdiri di depan silo
        # perlu tahu barang siapa yang di dalamnya, bukan sekadar bahwa ditolak.
        assert "JAS-" in e.value.args[0], e.value.args[0]


async def test_dua_pesanan_pelanggan_yang_sama_tetap_terpisah(pg, pemakai, pabrik):
    """Pembandingnya `jasa_id`, BUKAN `pelanggan_id`.

    Dua pesanan Pak Budi punya bobot kembali yang berbeda; mencampurnya membuat
    pesanan pertama tampak lunas oleh barang pesanan kedua.
    """
    from app.models import User
    from app.penggilingan.gudang1.services.silo import SiloError, masuk_silo

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        t1 = await _tiket(db, kode="JT40", berat=5_000, pelanggan_id=pid)
        t2 = await _tiket(db, kode="JT41", berat=5_000, pelanggan_id=pid,
                          nopol="B 8 UJ")
        await db.commit()
        nama_silo = "A"
    async with pg() as db:
        a = await _terima(db, t1, pemakai.id)
        kode_a, jid_a = a.batch.kode_batch, a.jasa.id
    async with pg() as db:
        # Tiket KEDUA tidak menunjuk pesanan pertama → pesanan BARU, sengaja.
        b = await _terima(db, t2, pemakai.id)
        kode_b = b.batch.kode_batch
        assert b.jasa.id != jid_a, "dua tiket tanpa penunjuk jadi satu pesanan"
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo=nama_silo, kode_lot=None,
                         kode_batch=kode_a)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(SiloError) as e:
            await masuk_silo(db, user=u, nama_silo=nama_silo, kode_lot=None,
                             kode_batch=kode_b)
        assert _PESAN_CAMPUR in e.value.args[0], e.value.args[0]


async def test_satu_pesanan_boleh_dua_silo_digiling_bersama(pg, pemakai, pabrik):
    """⭐ SEBALIKNYA: barang SEPEMILIK boleh dicampur sebebas barang pabrik.

    Keputusan pemilik: *"yang tidak memungkinkan adalah menggabungkan barang
    jika kepemilikan berbeda. itu saja batasannya."* Penjaga yang menolak ini
    akan menolak pekerjaan yang sah — dan penjaga yang menolak hal yang benar
    adalah penjaga yang dilangkahi orang.
    """
    from app.models import MillingProcess, User
    from app.penggilingan.gudang1.services.milling import start_milling
    from app.penggilingan.gudang1.services.silo import masuk_silo

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        t1 = await _tiket(db, kode="JT50", berat=6_000, pelanggan_id=pid)
        await db.commit()
    async with pg() as db:
        a = await _terima(db, t1, pemakai.id)
        jid, kode_a = a.jasa.id, a.batch.kode_batch
    async with pg() as db:
        t2 = await _tiket(db, kode="JT51", berat=6_000, pelanggan_id=pid,
                          jasa_id=jid, nopol="B 7 UJ")
        await db.commit()
    async with pg() as db:
        b = await _terima(db, t2, pemakai.id)
        kode_b = b.batch.kode_batch
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo="A", kode_lot=None, kode_batch=kode_a)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo="B", kode_lot=None, kode_batch=kode_b)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        hasil = await start_milling(db, user=u, nama_silo=["A", "B"])
    async with pg() as db:
        proc = (await db.execute(select(MillingProcess))).scalars().one()
        assert proc.jasa_id == jid, "lot dua silo sepemilik kehilangan pemiliknya"
        assert float(proc.berat_gabah_masuk_kg) == 12_000


async def test_giling_menolak_dua_silo_beda_pemilik(pg, pemakai, pemasok, pabrik):
    """Dua silo, dua pemilik, satu lot → DITOLAK.

    Satu lot berarti SATU rendemen atas seluruh bahannya; bahan dua pemilik
    membuat angka itu tak bisa dipertanggungjawabkan ke siapa pun.
    """
    from app.models import User
    from app.penggilingan.gudang1.services.milling import MillingError, start_milling
    from app.penggilingan.gudang1.services.silo import masuk_silo

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        t1 = await _tiket(db, kode="JT60", berat=6_000, pelanggan_id=pid)
        t2 = await _tiket(db, kode="JT61", berat=6_000, supplier_id=pemasok.id,
                          nopol="B 6 UJ")
        await db.commit()
    async with pg() as db:
        kode_a = (await _terima(db, t1, pemakai.id)).batch.kode_batch
    async with pg() as db:
        kode_b = (await _terima(db, t2, pemakai.id)).batch.kode_batch
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo="A", kode_lot=None, kode_batch=kode_a)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo="B", kode_lot=None, kode_batch=kode_b)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(MillingError) as e:
            await start_milling(db, user=u, nama_silo=["A", "B"])
        # Diperiksa ISI pesannya, bukan cuma bahwa ia melempar: `start_milling`
        # punya enam penolakan lain (silo kosong, sedang digiling, …) dan uji
        # yang menerima pesan apa pun akan tetap lulus pada hari penjaga
        # pemiliknya hilang — ia cuma akan ditolak oleh alasan yang lain.
        assert _PESAN_CAMPUR in e.value.args[0], e.value.args[0]


async def test_pengering_menolak_dua_pemilik(pg, pemakai, pemasok, pabrik):
    """Titik campur PERTAMA: mesin pengering, bukan pembentukan lotnya.

    Lot baru lahir saat "mulai pengeringan", sedangkan gabahnya sudah bercampur
    sejak masuk mesin. Menjaga pembentukan lot saja berarti menolak pada saat
    penolakannya sudah tak berguna — dua pemilik sudah di dalam satu mesin.
    """
    from app.models import User
    from app.penggilingan.gudang1.services.drying import DryingError, masuk_dryer

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        t1 = await _tiket(db, kode="JT70", berat=5_000, pelanggan_id=pid,
                          jenis="GABAH_BASAH")
        t2 = await _tiket(db, kode="JT71", berat=5_000, supplier_id=pemasok.id,
                          jenis="GABAH_BASAH", nopol="B 5 UJ")
        await db.commit()
    async with pg() as db:
        kode_a = (await _terima(db, t1, pemakai.id, kondisi="basah")).batch.kode_batch
    async with pg() as db:
        kode_b = (await _terima(db, t2, pemakai.id, kondisi="basah")).batch.kode_batch
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_dryer(db, user=u, kode_batch_list=[kode_a])
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(DryingError) as e:
            await masuk_dryer(db, user=u, kode_batch_list=[kode_b])
        # Isi pesannya diperiksa: keduanya gabah BASAH, jadi penjaga
        # basah/kering tak mungkin yang menolak — tetapi tanpa pemeriksaan ini,
        # penjaga kapasitas atau "mesin dipakai lot" akan menutupi hilangnya
        # penjaga pemilik tanpa satu uji pun berubah warna.
        assert _PESAN_CAMPUR in e.value.args[0], e.value.args[0]


# ══════════════ 3 · NULL = PABRIK, PERILAKU LAMA TAK BERGESER ══════════════

async def test_gabah_pabrik_tetap_boleh_dicampur_dalam_satu_silo(pg, pemakai,
                                                                 pemasok, pabrik):
    """Pencabutan larangan campur untuk gabah PABRIK (migrasi 0031) TETAP.

    Pagar silo yang dipasang ulang "sekalian" akan memacetkan pengeringan setiap
    kali kedua silo terisi — kemacetan yang justru melahirkan tumpukan, dan ia
    merugikan pabrik di jalur yang tak ada hubungannya dengan jasa.
    """
    from app.models import SiloStorage, User
    from app.penggilingan.gudang1.services.silo import masuk_silo

    async with pg() as db:
        t1 = await _tiket(db, kode="JT80", berat=4_000, supplier_id=pemasok.id)
        t2 = await _tiket(db, kode="JT81", berat=4_000, supplier_id=pemasok.id,
                          nopol="B 4 UJ")
        await db.commit()
    async with pg() as db:
        kode_a = (await _terima(db, t1, pemakai.id)).batch.kode_batch
    async with pg() as db:
        kode_b = (await _terima(db, t2, pemakai.id)).batch.kode_batch
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo="A", kode_lot=None, kode_batch=kode_a)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo="A", kode_lot=None, kode_batch=kode_b)
    async with pg() as db:
        baris = (await db.execute(select(SiloStorage))).scalars().all()
        assert len(baris) == 2
        assert {b.jasa_id for b in baris} == {None}


async def test_pk_jasa_tak_muncul_di_daftar_barang_yang_bisa_dijual(pg, pemakai, pabrik):
    """⚠ BAHAYA TERBESAR SELURUH PEKERJAAN INI, dan ia tak melempar galat.

    Tanpa saringan pemilik, Stok menghitung barang pelanggan sebagai stok pabrik
    dan pabrik akan menjualnya. Bukan angka yang salah — barang orang lain yang
    terjual, dan itu tak bisa diperbaiki dengan pembetulan pembukuan.

    Dua hal diuji bersama, sebab satu saja tidak cukup: daftarnya tak memuatnya,
    DAN penjaganya menolak bila kodenya tetap diketik.
    """
    from app.models import User
    from app.penggilingan.gudang1.services.milling import (finish_milling,
                                                           start_milling,
                                                           stok_pk_g1)
    from app.penggilingan.gudang1.services.silo import masuk_silo
    from app.services.barang_keluar import BarangKeluarError, BarisPerintah, tersedia
    from app.services.stok import pk_gudang1

    async with pg() as db:
        pid = await _pelanggan(db, "Bu Sri")
        tid = await _tiket(db, kode="JT90", berat=10_000, pelanggan_id=pid)
        await db.commit()
    async with pg() as db:
        kode_batch = (await _terima(db, tid, pemakai.id)).batch.kode_batch
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo="A", kode_lot=None,
                         kode_batch=kode_batch)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        proc = (await start_milling(db, user=u, nama_silo="A")).proc
        kode_proses, proc_id = proc.kode_proses, proc.id
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await finish_milling(db, user=u, kode_proses=kode_proses, berat_akhir=7_000)

    async with pg() as db:
        # Lotnya TETAP terdaftar di stok (barangnya memang ada di lantai) —
        # tetapi bertanda pemilik.
        lot = [x for x in await pk_gudang1(db) if x.kode == kode_proses]
        assert len(lot) == 1 and lot[0].jasa_id is not None
        assert lot[0].pemilik and lot[0].pemilik.startswith("JAS-")
        # Dan ia TIDAK ikut ke angka stok PABRIK.
        assert await stok_pk_g1(db) == 0, "PK pelanggan terhitung sebagai stok pabrik"
        assert await stok_pk_g1(db, termasuk_jasa=True) == 7_000

    async with pg() as db:
        with pytest.raises(BarangKeluarError):
            await tersedia(db, BarisPerintah(tipe="pk_langsung",
                                             milling_process_id=proc_id,
                                             berat_kg=1_000))



async def test_pembatalan_gabah_masuk_tak_meninggalkan_pesanan_yatim(pg, pemakai):
    """Tiket dibatalkan → pesanannya ikut, bila tak ada barangnya lagi.

    Pesanan BERJALAN tanpa satu kilogram pun di pabrik berdiri di daftar menuntut
    barang yang tak pernah ada — dan sisanya nol karena kosong, tak bisa
    dibedakan dari pesanan yang sudah diambil habis. Itu jebakan nol yang
    aturan "selesai" dibentuk untuk menghindarinya.
    """
    from app.models import Jasa, User
    from app.models.jasa import BERJALAN, DIBATALKAN
    from app.services import undo as svc

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        t1 = await _tiket(db, kode="JTA0", berat=6_000, pelanggan_id=pid)
        await db.commit()
    async with pg() as db:
        jid = (await _terima(db, t1, pemakai.id)).jasa.id
    async with pg() as db:
        t2 = await _tiket(db, kode="JTA1", berat=6_000, pelanggan_id=pid,
                          jasa_id=jid, nopol="B 3 UJ")
        await db.commit()
    async with pg() as db:
        await _terima(db, t2, pemakai.id)

    # Truk KEDUA dibatalkan: pesanannya TETAP berjalan — truk pertama masih ada.
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
        await svc.undo_last(db, actor=u, cakupan=c)
    async with pg() as db:
        assert (await db.get(Jasa, jid)).status == BERJALAN, \
            "pesanan dibatalkan padahal truk pertamanya masih ada"

    # Truk PERTAMA dibatalkan juga: sekarang tak ada barangnya lagi.
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
        await svc.undo_last(db, actor=u, cakupan=c)
    async with pg() as db:
        pesanan = await db.get(Jasa, jid)
        assert pesanan.status == DIBATALKAN, "pesanan yatim tertinggal berjalan"
        assert pesanan.dibatalkan_pada is not None


async def test_silo_g2_yang_sudah_dikosongkan_menerima_pemilik_lain(pg, pemakai,
                                                                    pabrik):
    """⚠ "Milik siapa SEKARANG", bukan "pernah milik siapa".

    Baris intake TIDAK dihapus saat PK-nya disosoh habis — riwayatnya tetap
    berdiri sementara `hitung_stok_silo` sudah nol. Penjaga yang membaca seluruh
    riwayat akan membuat silo yang sudah kosong menolak PK pabrik SELAMANYA, dan
    tak seorang pun bisa menebak sebabnya dari layar.

    Cacat ini pernah ada di `pemilik_silo_g2` dan ditemukan saat meninjau
    sendiri — uji ini yang menahannya supaya tak kembali.
    """
    from app.models import Jasa, PolishingSiloUsage, Silo, User, Warehouse
    from app.penggilingan.gudang2.service import _add_intake, get_g2_silo

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        j = Jasa(kode="JAS-UJI-900", pelanggan_id=pid)
        db.add(j)
        await db.flush()
        jid = j.id
        await db.commit()

    # 1 · PK jasa masuk silo A.
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await _add_intake(db, user=u, sumber_tipe="transfer_internal", tujuan="A",
                          berat_kg=4_000, hpp_per_kg=None, tanggal=None, jam=None,
                          jasa_id=jid)

    # 2 · Disosoh HABIS — stok silo kembali nol, barisnya tetap ada.
    async with pg() as db:
        from app.penggilingan.gudang2.models import PolishingProcess
        silo = await get_g2_silo(db, "A")
        pr = PolishingProcess(kode_proses="POL-UJI-900", waktu_mulai=_sekarang(),
                              waktu_selesai=_sekarang(), status="selesai",
                              created_by=pemakai.id)
        db.add(pr)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=pr.id, silo_id=silo.id,
                                  berat_awal_kg=4_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=4_000))
        await db.commit()
        sid = silo.id

    async with pg() as db:
        from app.penggilingan.gudang2.service import hitung_stok_silo
        from app.services.jasa import pemilik_silo_g2
        assert float(await hitung_stok_silo(db, sid)) <= 0.001
        assert await pemilik_silo_g2(db, sid) == set(), \
            "silo yang sudah kosong masih mengaku bertuan"

    # 3 · PK PABRIK boleh masuk silo yang sama — inilah yang dulu ditolak.
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await _add_intake(db, user=u, sumber_tipe="beli_luar", tujuan="A",
                          berat_kg=3_000, hpp_per_kg=None, tanggal=None, jam=None)
    async with pg() as db:
        from app.services.jasa import pemilik_silo_g2
        assert await pemilik_silo_g2(db, sid) == {None}, \
            "pemilik silo tak ikut berpindah ke muatan yang baru"




# ═══════════ 5 · SAMPAI BERAS: rantai Gudang 2 (migrasi 0065) ═══════════
#
# Sampai migrasi 0065 penyosohan MENOLAK PK jasa, sebab `polishing_process`
# belum bisa memikul pemilik. Uji penolakan itu DICABUT bersama penjaganya —
# penjaga yang menolak hal yang sudah sah adalah penjaga yang dilangkahi orang.
# Yang menggantikannya: pemiliknya terbawa, dan bekatulnya beralih milik.


async def _pk_jasa_di_silo_g2(pg, pemakai, nama_silo="A", berat=5_000.0,
                              pelanggan="Bu Sri", kode="JAS-UJI-500"):
    """Satu silo Gudang 2 berisi PK milik satu pesanan jasa. → (jasa_id, silo_id)"""
    from app.models import Jasa, Silo, User
    from app.penggilingan.gudang2.service import _add_intake, get_g2_silo

    async with pg() as db:
        pid = await _pelanggan(db, pelanggan)
        j = Jasa(kode=kode, pelanggan_id=pid)
        db.add(j)
        await db.flush()
        jid = j.id
        await db.commit()
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await _add_intake(db, user=u, sumber_tipe="transfer_internal",
                          tujuan=nama_silo, berat_kg=berat, hpp_per_kg=None,
                          tanggal=None, jam=None, jasa_id=jid)
    async with pg() as db:
        silo = await get_g2_silo(db, nama_silo)
        return jid, silo.id


async def test_penyosohan_membawa_pemilik(pg, pemakai, pabrik):
    """Proses sosoh mewarisi pemilik dari silonya — dan dari situ hasilnya."""
    from app.models import PolishingProcess, User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan

    jid, _ = await _pk_jasa_di_silo_g2(pg, pemakai)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await mulai_penyosohan(db, user=u, nama_silos=["A"])
    async with pg() as db:
        proc = (await db.execute(select(PolishingProcess))).scalars().one()
        assert proc.jasa_id == jid, "proses sosoh kehilangan pemiliknya"


async def test_penyosohan_menolak_dua_pemilik(pg, pemakai, pabrik):
    """Dua silo, dua pemilik, satu proses sosoh → DITOLAK.

    Satu proses = satu rendemen atas seluruh bahannya, dan beras yang keluar
    tak bisa dibagi kembali — tak ada lapisan di dalam mesin.
    """
    from app.models import User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import Gudang2Error
    from app.services.jasa import _PESAN_CAMPUR

    await _pk_jasa_di_silo_g2(pg, pemakai, "A", kode="JAS-UJI-510",
                              pelanggan="Pak Budi")
    await _pk_jasa_di_silo_g2(pg, pemakai, "B", kode="JAS-UJI-511",
                              pelanggan="Bu Sri")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(Gudang2Error) as e:
            await mulai_penyosohan(db, user=u, nama_silos=["A", "B"])
        assert _PESAN_CAMPUR in e.value.args[0], e.value.args[0]


async def test_bekatul_beralih_milik_tetapi_asalnya_terbaca(pg, pemakai, pabrik):
    """⭐⭐ DUA FAKTA YANG BERPISAH, dan keduanya harus bertahan.

    Keputusan pemilik 12: *"bekatul tidak kembali bukan berarti barangnya tidak
    boleh keluar. bekatul otomatis berubah kepemilikan jadi milik kami. tetapi
    pemilik barang juga harus tau hasil bekatul dari tiap proses barang
    miliknya."*

        MILIK = pabrik          → `byproduct_stock.jasa_id` NULL
        ASAL  = JAS-UJI-520     → lewat `source_id` → `polishing_process.jasa_id`

    Rancangan yang menyimpan keduanya di satu kolom akan menghilangkan salah
    satunya. Uji ini menahan KEDUANYA sekaligus: itu sebabnya ia satu uji, bukan
    dua.
    """
    from app.models import ByproductStock, PolishingProcess, User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.inventory.finished_goods import (catat_bekatul,
                                                           hitung_stok_bekatul)

    jid, _ = await _pk_jasa_di_silo_g2(pg, pemakai, kode="JAS-UJI-520")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        kode_pol = r.proc.kode_proses
    # Hasil sosoh dicatat, lalu bekatulnya dibukukan curah.
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        from app.penggilingan.gudang2.polishing import catat_output
        await catat_output(db, user=u, kode=kode_pol, jenis="bekatul",
                           berat_kg=400)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await catat_bekatul(db, user=u, kode_pol=kode_pol, berat_kg=400)

    async with pg() as db:
        bk = (await db.execute(select(ByproductStock))).scalars().one()
        # ① MILIK: pabrik. Bukan kelalaian — itu yang pemilik putuskan.
        assert bk.jasa_id is None, "bekatul jadi stok pelanggan"
        # ② ASAL: tetap terbaca lewat prosesnya, tanpa kolom tambahan.
        proc = await db.get(PolishingProcess, bk.source_id)
        assert proc is not None and proc.jasa_id == jid, "asal bekatul hilang"
        # ③ Dan ia stok pabrik BIASA — boleh dijual, tanpa penghalang.
        assert float(await hitung_stok_bekatul(db)) == 400


async def test_beras_jasa_bukan_stok_pabrik(pg, pemakai, pabrik):
    """⚠⚠ BAHAYA TERBESAR SELURUH PEKERJAAN JASA, dan ia tak melempar galat.

    Tanpa saringan pemilik, Stok Produk menghitung beras pelanggan sebagai stok
    pabrik lalu pabrik menjualnya — bukan angka yang salah, barang orang lain
    yang terjual, dan itu tak bisa diperbaiki dengan pembetulan pembukuan.
    """
    from app.models import FinishedGoodsStock, User
    from app.penggilingan.gudang2.polishing import catat_output, mulai_penyosohan
    from app.penggilingan.inventory.finished_goods import (catat_packing,
                                                           hitung_stok_finished_goods)
    # Master produk (standar mutu, SKU, kemasan, ukuran) dari penyemai yang
    # SAMA yang dipakai app — bukan disusun tangan di sini: baris master yang
    # dikarang uji akan berbeda dari yang sungguhan, dan yang pertama gagal
    # justru pemetaan nama produknya.
    from app.services.seed import seed_master

    await seed_master()
    jid, _ = await _pk_jasa_di_silo_g2(pg, pemakai, kode="JAS-UJI-530")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        kode_pol = (await mulai_penyosohan(db, user=u, nama_silos=["A"])).proc.kode_proses
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await catat_output(db, user=u, kode=kode_pol, jenis="medium",
                           berat_kg=3_000)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await catat_packing(db, user=u, kode_pol=kode_pol, kategori="beras_putih",
                            grade="medium", material_kode="biasa", ukuran=25,
                            jumlah_karung=120)          # 3.000 kg

    async with pg() as db:
        fg = (await db.execute(select(FinishedGoodsStock))).scalars().one()
        # ① Berasnya milik PEMILIKNYA — kembali, bukan ditahan.
        assert fg.jasa_id == jid, "beras pelanggan dibukukan milik pabrik"
        # ② Dan ia TIDAK terhitung sebagai stok pabrik yang boleh dijual.
        stok = await hitung_stok_finished_goods(
            db, fg.product_sku_id, fg.rice_quality_standard_id)
        assert float(stok["kg"]) == 0, \
            f"beras pelanggan terhitung stok pabrik: {stok}"


# ═══════════ 6 · PENGAMBILAN, "SELESAI", DAN NOTANYA ═══════════


async def _pk_jasa_walk_in(pg, admin, *, berat=5_000.0, kode_tiket="JTP0",
                           pelanggan="Bu Sri") -> int:
    """PK jasa dari LUAR, lewat jalur sungguhannya: tiket → batch → silo G2.

    ⚠ Dipakai menggantikan penyisipan `_add_intake` langsung, dan sebabnya
    ditemukan uji: pesanan yang barangnya disisipkan tanpa batch terbaca "belum
    pernah menerima barang" — lalu ia bisa dibatalkan sementara barangnya sudah
    di silo. Fixture yang melompati jalur nyata menguji jalur yang tak ada.
    """
    from app.models import User
    from app.penggilingan.gudang2.service import (create_pk_purchase_dari_timbang,
                                                  masukkan_pk_luar)

    async with pg() as db:
        pid = await _pelanggan(db, pelanggan)
        tid = await _tiket(db, kode=kode_tiket, berat=berat, pelanggan_id=pid,
                           jenis="BERAS_PK", nopol="AD 1 PK")
        await db.commit()
    async with pg() as db:
        u = await db.get(User, admin.id)
        r = await create_pk_purchase_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, jenis_pk="KL")
        kode_batch, jid = r.batch.kode_batch, r.batch.jasa_id
        assert r.batch.supplier_id is None, "PK titipan jadi pembelian"
    async with pg() as db:
        u = await db.get(User, admin.id)
        await masukkan_pk_luar(db, user=u, kode=kode_batch, tujuan="A")
    return jid


async def _pesanan_sampai_beras(pg, pemakai, admin, kode_tiket="JTP0",
                                karung=120, pelanggan="Bu Sri",
                                bekatul_kg: float = 0.0):
    """Satu pesanan PK jasa yang sudah disosoh & dikemas. → (jasa_id, sku, std)

    Penyosohannya DITUTUP, bukan dibiarkan berjalan: selama ia terbuka, isi
    silo Gudang 2 masih terbaca utuh di seluruh app (`hitung_stok_silo`
    mengurangi hanya saat `berat_akhir_kg` terisi), jadi `sisa_jasa` pun
    menyebut PK-nya masih ada — benar, dan sengaja sama dengan layar stok.
    """
    from app.models import FinishedGoodsStock, User
    from app.penggilingan.gudang2.polishing import (catat_output,
                                                    mulai_penyosohan,
                                                    selesai_penyosohan)
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.seed import seed_master

    await seed_master()
    jid = await _pk_jasa_walk_in(pg, admin, kode_tiket=kode_tiket,
                                 pelanggan=pelanggan)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        kode_pol = (await mulai_penyosohan(db, user=u, nama_silos=["A"])).proc.kode_proses
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await catat_output(db, user=u, kode=kode_pol, jenis="medium",
                           berat_kg=karung * 25)
        # Hasil samping dicatat SEBELUM prosesnya ditutup — sesudahnya
        # `catat_output` menolak, dan benar: hasil yang muncul setelah mesin
        # dinyatakan berhenti adalah hasil yang tak punya prosesnya.
        if bekatul_kg:
            await catat_output(db, user=u, kode=kode_pol, jenis="bekatul",
                               berat_kg=bekatul_kg)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        # Sisa nol: seluruh PK-nya habis jadi beras & hasil samping. Silonya
        # disebut satu per satu — `selesai_penyosohan` menandai SATU silo, dan
        # prosesnya baru selesai saat semuanya ditandai.
        await selesai_penyosohan(db, user=u, kode=kode_pol, nama_silo="A",
                                 sisa_kg=0)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await catat_packing(db, user=u, kode_pol=kode_pol, kategori="beras_putih",
                            grade="medium", material_kode="biasa", ukuran=25,
                            jumlah_karung=karung)
    async with pg() as db:
        fg = (await db.execute(select(FinishedGoodsStock).where(
            FinishedGoodsStock.jasa_id == jid))).scalars().first()
        return jid, fg.product_sku_id, fg.rice_quality_standard_id


async def test_sisa_jasa_tidak_pernah_dijumlah_jadi_satu_angka(pg, pemakai, admin, pabrik):
    """Rincian PER FASE, dan `fase` diturunkan dari tempat barangnya.

    Satu angka gabungan akan menghitung beras yang sama dua sampai tiga kali —
    dan angka itu dipakai orang memutuskan berapa yang harus diserahkan.
    """
    from app.services.jasa import sisa_jasa

    jid, _, _ = await _pesanan_sampai_beras(pg, pemakai, admin)
    async with pg() as db:
        s = await sisa_jasa(db, jid)
        assert s.barang_jadi_kg == 3_000
        assert s.pk_g2_kg == 0, "PK yang sudah disosoh masih dihitung ada"
        assert s.fase == "beras"
        assert s.ada


async def test_pesanan_baru_belum_selesai_walau_sisanya_nol(pg, pemakai):
    """⚠ JEBAKAN NOL, dan ia yang membuat aturan "selesai" perlu dua syarat.

    Pesanan yang baru dibuat sementara truknya belum datang juga punya sisa NOL.
    Tanpa syarat "pernah ada barang masuk", ia akan terbaca selesai pada detik
    ia lahir — lalu pelanggannya datang ke pesanan yang sudah ditutup.
    """
    from app.models import Jasa
    from app.services.jasa import boleh_ditutup

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        j = Jasa(kode="JAS-UJI-710", pelanggan_id=pid)
        db.add(j)
        await db.flush()
        jid = j.id
        await db.commit()
    async with pg() as db:
        boleh, sebab = await boleh_ditutup(db, jid)
        assert not boleh
        assert "Belum ada barang masuk" in sebab, sebab


async def test_pengambilan_mengurangi_pesanan_bukan_stok_pabrik(pg, pemakai, admin, pabrik):
    """⚠⚠ DUA KESALAHAN DARI SATU SARINGAN YANG TERLUPA.

    Kalau yang KELUAR tak ikut disaring pemilik, pengambilan pelanggan akan
    dikurangkan dari stok PABRIK: stok pabrik menyusut karena barang orang lain
    diambil, dan pesanan jasanya tampak tak pernah berkurang. Uji ini menahan
    keduanya sekaligus — itu sebabnya ia memeriksa DUA angka.
    """
    from app.models import User
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    from app.services import barang_keluar as bk
    from app.services.jasa import sisa_jasa

    jid, sku, std = await _pesanan_sampai_beras(pg, pemakai, admin)
    async with pg() as db:
        pabrik_sebelum = float(
            (await hitung_stok_finished_goods(db, sku, std))["kg"])

    # Perintah pengambilan 50 karung (1.250 kg), lalu dimuat seluruhnya.
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        r = await bk.buat_perintah(
            db, user=u, jasa_id=jid,
            baris=[bk.BarisPerintah(tipe="finished_goods", sku_id=sku,
                                    std_id=std, jumlah_karung=50)],
            no_polisi="AD 7 JASA")
        rec_id = r.rec.id
        # Pembelinya PEMILIKNYA, dan tak ditanya siapa pun.
        assert r.rec.jasa_id == jid
        assert r.rec.nama_pembeli == "Bu Sri"
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        # ① Pesanannya berkurang.
        s = await sisa_jasa(db, jid)
        assert s.barang_jadi_kg == 1_750, s.barang_jadi_kg
        # ② Stok PABRIK tidak tersentuh sama sekali.
        assert float((await hitung_stok_finished_goods(db, sku, std))["kg"]) \
            == pabrik_sebelum


async def test_pesanan_ditutup_hanya_setelah_barangnya_habis(pg, pemakai, admin, pabrik):
    """SELESAI = pernah ada barang masuk DAN tak ada lagi barangnya di pabrik."""
    from app.models import Jasa, User
    from app.models.jasa import SELESAI
    from app.services import barang_keluar as bk
    from app.services.jasa import JasaError, tutup_pesanan

    jid, sku, std = await _pesanan_sampai_beras(pg, pemakai, admin,
                                               kode_tiket="JTP2")

    # Masih ada barangnya → DITOLAK, dan penolakannya menyebut di mana.
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(JasaError) as e:
            await tutup_pesanan(db, user=u, jasa_id=jid)
        assert "Masih ada barang" in e.value.args[0], e.value.args[0]

    # Diambil SELURUHNYA (120 karung = 3.000 kg).
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        r = await bk.buat_perintah(
            db, user=u, jasa_id=jid,
            baris=[bk.BarisPerintah(tipe="finished_goods", sku_id=sku,
                                    std_id=std, jumlah_karung=120)],
            no_polisi="AD 8 JASA")
        rec_id = r.rec.id
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        pesan = await tutup_pesanan(db, user=u, jasa_id=jid)
        assert "SELESAI" in pesan
    async with pg() as db:
        assert (await db.get(Jasa, jid)).status == SELESAI


async def test_nota_memisahkan_bekatul_dari_total_kembali(pg, pemakai, admin, pabrik):
    """⭐ TIGA hal dalam bentuk nota yang tidak boleh digeser.

    1. bekatul DI LUAR "Total kembali" — ia tidak kembali, jadi
       menjumlahkannya akan berbohong tentang apa yang diterima;
    2. bekatul PER PROSES SOSOH, bukan satu angka gabungan;
    3. selisihnya SATU baris yang mengaku TIDAK DIUKUR TERPISAH — sekam tak
       bisa dideteksi dan bobot gabah kering tak pernah diukur, jadi nota yang
       menyebut sebab terukur akan ditanyai rinciannya.
    """
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingProcess
    from app.penggilingan.inventory.finished_goods import catat_bekatul
    from app.services.jasa import nota_jasa

    jid, _, _ = await _pesanan_sampai_beras(pg, pemakai, admin,
                                           kode_tiket="JTP3", bekatul_kg=300)
    async with pg() as db:
        kode_pol = (await db.execute(select(PolishingProcess.kode_proses).where(
            PolishingProcess.jasa_id == jid))).scalars().one()
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await catat_bekatul(db, user=u, kode_pol=kode_pol, berat_kg=300)

    async with pg() as db:
        teks = await nota_jasa(db, jid)

    assert "Total kembali" in teks
    # Bekatulnya disebut, PER PROSES, dan di bagian yang terpisah.
    assert "BERALIH MILIK" in teks
    assert kode_pol in teks.split("BERALIH MILIK")[1], \
        "bekatul tidak dirinci per proses sosoh"
    # Dan ia TIDAK ikut ke "Total kembali": belum ada yang diambil sama sekali.
    blok_kembali = teks.split("Total kembali")[1].splitlines()[0]
    assert "0 kg" in blok_kembali, blok_kembali
    # Selisihnya mengaku tidak diukur terpisah — tak boleh menyebut sebab
    # terukur, sebab pabrik tidak tahu bagian mana air dan bagian mana sekam.
    assert "tidak diukur terpisah" in teks
    assert "susut pengeringan, sekam & susut proses" in teks


# ═════════ 7 · DISARING BUKAN BERARTI DISEMBUNYIKAN ═════════
#
# Laporan lapangan 2 Oktober 2026, dari pemilik: *"pk yang selesai digiling
# tidak terlihat di stock oleh admin dan operator gudang 2. kalau ternyata jasa
# sampai beras putih harusnya barang bisa dipindahkan ke gudang 2."*
#
# Keduanya terbukti BUKAN masalah izin: layar `/stok` mendaftar lot jasanya,
# dan rantai permintaan→setujui→kirim menerimanya utuh sampai silo Gudang 2.
# Yang rusak ANGKA KEPALANYA — Beranda, baris gudang, dan papan Direksi
# menyebut "PK 0 kg" sementara tujuh ton barang pelanggan berdiri di lantai,
# karena ketiganya saya saring jadi milik-pabrik tanpa menyebut titipannya di
# sebelahnya. Operator lalu menyimpulkan tak ada apa-apa untuk dipindahkan.
#
# Jadi aturannya PUNYA DUA SISI, dan bagian ini menjaga sisi keduanya:
#
#     jangan pernah MENGHITUNG barang pelanggan sebagai milik pabrik
#     jangan pernah MENGHILANGKANNYA dari layar
#
# Saringan tanpa penyebutan sama berbahayanya dengan penjumlahan: yang pertama
# membuat pabrik menjual barang orang lain, yang kedua membuat pabrik
# membiarkannya membusuk di lantai sambil mengira gudangnya kosong.

async def _pk_jasa_di_lantai_g1(pg, pemakai, *, kode_tiket="JLH1",
                                berat=10_000.0, hasil=7_000.0):
    """Satu pesanan jasa yang sudah jadi PK dan berdiri di lantai Gudang 1."""
    from app.models import User
    from app.penggilingan.gudang1.services.milling import (finish_milling,
                                                           start_milling)
    from app.penggilingan.gudang1.services.silo import masuk_silo

    async with pg() as db:
        pid = await _pelanggan(db, "Pak Budi")
        tid = await _tiket(db, kode=kode_tiket, berat=berat, pelanggan_id=pid)
        await db.commit()
    async with pg() as db:
        r = await _terima(db, tid, pemakai.id)
        jid, kode_batch = r.jasa.id, r.batch.kode_batch
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo="A", kode_lot=None,
                         kode_batch=kode_batch)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        kode_proses = (await start_milling(db, user=u, nama_silo="A")).proc.kode_proses
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await finish_milling(db, user=u, kode_proses=kode_proses,
                             berat_akhir=hasil)
    return jid, kode_proses


async def test_pk_jasa_disebut_di_angka_kepala_bukan_dihilangkan(pg, pemakai, pabrik):
    """⭐ INTI LAPORANNYA: angka pabrik tetap 0, titipannya DISEBUT.

    Diuji BERSAMA, bukan masing-masing — yang berbahaya justru tiap setengahnya
    sendiri. `stok_pk == 7000` berarti pabrik melihat barang orang lain sebagai
    persediaannya (dan akan menjualnya); `jasa_pk == 0` berarti tujuh ton
    menghilang dari layar yang orang buka lebih dulu (dan tak akan dikerjakan).
    Hanya dua angka berdampingan yang benar.
    """
    from app.penggilingan.gudang1.services.milling import (stok_pk_g1,
                                                           stok_pk_g1_pemilik)
    from app.services.beranda import angka_gudang, baris_gudang, petak_pabrik

    await _pk_jasa_di_lantai_g1(pg, pemakai, hasil=7_000)

    async with pg() as db:
        pabrik_kg, jasa_kg = await stok_pk_g1_pemilik(db)
        assert pabrik_kg == 0, "PK titipan terhitung sebagai stok pabrik"
        assert jasa_kg == pytest.approx(7_000), "PK titipan tidak terbaca"
        # Dan `stok_pk_g1` tetap diturunkan dari situ, satu rumus dua jawaban.
        assert await stok_pk_g1(db) == pytest.approx(pabrik_kg)
        assert await stok_pk_g1(db, termasuk_jasa=True) == pytest.approx(7_000)

        a = await angka_gudang(db)

    assert a["g1"]["stok_pk"] == 0
    assert a["g1"]["jasa_pk"] == pytest.approx(7_000)

    # Baris gudang: kata "titipan" dan angkanya, bukan angka tanpa nama.
    baris = {b["id"]: b["ket"] for b in baris_gudang(a, [], [])}
    assert "titipan" in baris["g1"], baris["g1"]
    assert "7.000" in baris["g1"], baris["g1"]

    # Petak "Stok PK": nilainya tetap MILIK PABRIK, titipannya di keterangan.
    petak = {p["label"]: p for p in petak_pabrik(a, [])}
    assert petak["Stok PK"]["nilai"] == "0"
    assert "titipan" in petak["Stok PK"]["ket"], petak["Stok PK"]["ket"]


async def test_papan_direksi_mendaftar_pk_titipan_berikut_kode_pesanannya(
        pg, pemakai, pabrik):
    """Papan Direksi juga, dan dengan KODE pesanannya.

    Angka tanpa kode tak bisa ditindaklanjuti: yang perlu diputuskan atas PK
    titipan adalah "pesanan siapa ini, dan sudah berapa lama" — jawabannya ada
    di layar Jasa, dan kodenya satu-satunya jalan ke sana.
    """
    from app.services.dashboard import _stok_pk

    await _pk_jasa_di_lantai_g1(pg, pemakai, kode_tiket="JLH2", hasil=7_000)

    async with pg() as db:
        s = await _stok_pk(db)

    assert s["total"] == 0, "PK titipan terhitung sebagai stok pabrik"
    assert s["jasa_total"] == pytest.approx(7_000)
    assert len(s["jasa_proses"]) == 1
    assert s["jasa_proses"][0]["jasa"].startswith("JAS-")
    assert "Pak Budi" in s["jasa_proses"][0]["jasa"]
    # Dan lot jasanya TIDAK menyusup ke daftar pabrik.
    assert all("JAS-" not in str(p) for p in s["per_proses"])


async def test_lot_pk_jasa_tetap_boleh_diminta_gudang_2_dan_bertanda(pg, pemakai,
                                                                     pabrik):
    """⭐ Sisi kedua laporannya: "harusnya barang bisa dipindahkan ke gudang 2".

    Picker permintaan G2 adalah KEBALIKAN dari dua picker penjualan: menyosoh
    barang pelanggan adalah pekerjaan yang dipesan, jadi lotnya DITAWARKAN.
    Yang dilarang menjualnya, bukan memindahkannya.

    Tetapi pemiliknya wajib disebut di labelnya. Operator yang memindahkan
    tujuh ton tanpa tahu itu titipan akan memperlakukannya seperti stok pabrik
    begitu barangnya sampai — dan keputusan paling mahal di jalur ini (dijual
    atau dikembalikan) diambil dari label yang ia baca di sini.
    """
    import pathlib

    from app.services.stok import pk_gudang1

    jid, kode_proses = await _pk_jasa_di_lantai_g1(pg, pemakai,
                                                   kode_tiket="JLH3")

    async with pg() as db:
        lot = [l for l in await pk_gudang1(db) if l.kode == kode_proses]
    assert lot, "lot PK jasa hilang dari daftar stok PK Gudang 1"
    l = lot[0]
    assert l.tersedia > 0
    assert l.jasa_id == jid
    # `pemilik` dipakai DUA pembaca: label picker `/actions/pk-g1-tersedia`
    # dan kartu stoknya. Ia sempat dihitung lalu tak pernah digambar.
    assert l.pemilik and "Pak Budi" in l.pemilik, l.pemilik

    # Dan picker-nya memang menyebutnya. Dibaca dari SUMBER, bukan dipanggil:
    # memanggilnya butuh sesi operator Gudang 2 yang sudah diuji di
    # `test_stok_pk_g1_polesan.py`, sementara yang rapuh di sini satu hal saja
    # — labelnya berhenti menyebut pemiliknya saat seseorang merapikan f-string
    # yang panjang itu.
    sumber = pathlib.Path("app/web/api.py").read_text()
    blok = sumber.split("async def pk_g1_tersedia")[1].split("\n@router")[0]
    assert "l.pemilik" in blok, "label picker permintaan G2 tak menyebut pemiliknya"
    assert "TITIPAN" in blok, "labelnya tak menyebut bahwa barangnya titipan"
    # ⚠ Dan ia TIDAK boleh menyaring lot jasa seperti dua picker PENJUALAN:
    # menyosoh barang pelanggan adalah pekerjaan yang dipesan.
    assert "l.jasa_id is None" not in blok, \
        "picker permintaan G2 ikut membuang lot jasa — barangnya jadi tak bisa dipindah"


async def test_silo_g2_titipan_tak_hilang_dari_angka_dan_tak_jadi_milik_pabrik(
        pg, pemakai, pabrik):
    """Gudang 2 juga — dan di sini ada jebakan tambahan.

    Stok silo G2 = masuk langsung + masuk lewat tumpukan − TERPAKAI penyosohan.
    Saringan pemiliknya dulu dipasang pada dua yang MASUK saja; `terpakai` tak
    disaring sama sekali. Akibatnya satu proses sosoh barang pelanggan
    mengurangi stok PABRIK silo itu — angkanya turun, bisa sampai negatif, dan
    tak ada satu pun galat yang menyebutnya.

    Jadi yang diuji bukan cuma "titipannya terbaca", melainkan juga
    "pabrik + jasa = semua" — satu-satunya bentuk yang membuktikan ketiga
    bagian hitungannya memakai saringan yang sama.
    """
    from app.models import User
    from app.penggilingan.gudang2.polishing import (catat_output,
                                                     mulai_penyosohan,
                                                     selesai_penyosohan)
    from app.penggilingan.gudang2.service import (get_g2_silo, hitung_stok_silo,
                                                  hitung_stok_tumpukan)
    from app.services.beranda import angka_gudang
    from app.services.seed import seed_master
    from app.services.transfer import create_internal_transfer

    await seed_master()

    jid, kode_proses = await _pk_jasa_di_lantai_g1(pg, pemakai,
                                                   kode_tiket="JLH4")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await create_internal_transfer(db, user=u, kode_proses=kode_proses,
                                       lokasi_tujuan="A", berat=3_000)

    async with pg() as db:
        silo = await get_g2_silo(db, "A")
        semua = await hitung_stok_silo(db, silo.id)
        milik_pabrik = await hitung_stok_silo(db, silo.id, pemilik="pabrik")
        milik_jasa = await hitung_stok_silo(db, silo.id, pemilik="jasa")

    assert semua == pytest.approx(3_000)
    assert milik_pabrik == 0, "PK titipan terhitung sebagai stok pabrik"
    assert milik_jasa == pytest.approx(3_000), "PK titipan hilang dari angkanya"
    assert milik_pabrik + milik_jasa == pytest.approx(semua)

    # ── DAN SEKARANG SOSOHNYA DIJALANKAN ──
    #
    # Tanpa langkah ini `terpakai` nol, dan invarian di atas lulus dengan
    # sendirinya — uji yang memeriksa aturan tanpa membangkitkan keadaan yang
    # melanggarnya cuma menuliskan aturannya. Sesudah 1.000 kg barang PELANGGAN
    # disosoh, cabang "pabrik" yang tak menyaring `terpakai` akan menjawab
    # −1.000 kg: stok pabrik NEGATIF karena pekerjaan atas barang orang lain.
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        kode_pol = (await mulai_penyosohan(db, user=u,
                                           nama_silos=["A"])).proc.kode_proses
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await catat_output(db, user=u, kode=kode_pol, jenis="medium",
                           berat_kg=800)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await selesai_penyosohan(db, user=u, kode=kode_pol, nama_silo="A",
                                 sisa_kg=2_000)

    async with pg() as db:
        silo = await get_g2_silo(db, "A")
        semua2 = await hitung_stok_silo(db, silo.id)
        pabrik2 = await hitung_stok_silo(db, silo.id, pemilik="pabrik")
        jasa2 = await hitung_stok_silo(db, silo.id, pemilik="jasa")

    assert semua2 == pytest.approx(2_000), "sisa fisik silo salah"
    assert pabrik2 == 0, \
        f"sosoh barang pelanggan mengurangi stok PABRIK: {pabrik2} kg"
    assert pabrik2 >= 0, "stok pabrik tak boleh pernah negatif"
    assert jasa2 == pytest.approx(2_000)
    assert pabrik2 + jasa2 == pytest.approx(semua2)

    # Dan angka Beranda SESUDAH sosoh — lewat jalur susunnya yang sebenarnya,
    # bukan memanggil penghitungnya langsung. `jasa_pk` Gudang 2 menjumlahkan
    # silo DAN tumpukan, jadi saringan yang terlewat di salah satunya gagal
    # justru pada bentuk yang dibaca orang.
    async with pg() as db:
        for milik in ("pabrik", "jasa"):
            # Tumpukan G2 punya ketiga nilai yang sama — dipanggil supaya
            # "jasa" yang belum ada di sana gagal di sini, bukan di gudang.
            assert await hitung_stok_tumpukan(db, pemilik=milik) == 0
        a = await angka_gudang(db)

    assert a["g2"]["stok_pk"] == 0, "sisa titipan terbaca sebagai stok pabrik"
    assert a["g2"]["jasa_pk"] == pytest.approx(2_000)


async def test_layar_stok_menggambar_pemiliknya_bukan_cuma_menghitungnya(
        pg, pemakai, pabrik):
    """⭐ Pemilik yang dihitung lalu tak digambar sama saja dengan tak dihitung.

    `LotPk.pemilik` dan `TempatPk.pemilik` sempat ada di dataclass-nya dan TAK
    PERNAH disebut templatnya — jadi tumpukan penuh barang pelanggan tampak
    persis seperti tumpukan pabrik di layar yang justru dibuka untuk
    memutuskan.

    ⚠ Tujuannya TUMPUKAN, bukan silo (sejak 4 Oktober 2026 kartu silo
    dihapus dari `/stok` — keputusan pemilik: silo tak boleh menyimpan stok
    berdiri). Titipan yang berakhir di SILO tetap terbaca, tetapi lewat
    `/jasa` ("Di silo", lihat `jasa.html`) — bukan lagi lewat kartu ini.
    Kartu `/stok` sekarang hanya bertanggung jawab atas lot Gudang 1 dan
    Tumpukan Gudang 2, jadi itulah yang diuji di sini.

    DIRENDER SUNGGUHAN lewat HTTP, bukan dihitung kemunculan teksnya di
    markup-nya. Penjaga versi hitung-teks saya tulis lebih dulu dan ia LULUS
    saat markupnya dimatikan dengan `{% if false %}`: tulisan `{{ l.pemilik }}`
    tetap ada di berkasnya, cuma tak pernah tergambar. Penjaga yang polanya
    kurang lengkap lebih buruk daripada tak ada penjaga.

    Keduanya diperiksa pada SATU layar dan untuk DUA peran: admin yang menjual
    dan operator Gudang 2 yang menyosoh membaca kartu yang sama, dan keduanya
    memutuskan hal berbeda atas barang yang sama.
    """
    import httpx
    from app.main import app
    from app.models import ProduksiAkun, User, Warehouse
    from app.services.transfer import create_internal_transfer
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    _, kode_proses = await _pk_jasa_di_lantai_g1(pg, pemakai, kode_tiket="JLH5")
    # Separuh dipindah ke Gudang 2: satu layar lalu memuat KEDUA kartunya.
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await create_internal_transfer(db, user=u, kode_proses=kode_proses,
                                       lokasi_tujuan="ditumpuk", berat=3_000)

    async def klien(peran: str, gudang: str | None):
        async with pg() as db:
            wid = None
            if gudang:
                w = (await db.execute(select(Warehouse).where(
                    Warehouse.nama_gudang.like(gudang + "%")))).scalars().first()
                wid = w.id if w else None
            u = User(nama=f"Uji {peran}", role=peran, status="aktif",
                     default_warehouse_id=wid)
            db.add(u)
            await db.flush()
            a = ProduksiAkun(user_id=u.id, username=f"uji_lihat{u.id}",
                             password_hash=S.hash_sandi("rahasia123"),
                             status="aktif", mode_perangkat=mode_bawaan(peran))
            db.add(a)
            await db.commit()
            tok = security.buat_token(a)
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                              base_url="http://uji", follow_redirects=True)
        c.cookies.set(security.NAMA_COOKIE, tok)
        c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
        return c

    for peran, gudang in (("admin", None), ("operator", "Gudang 2")):
        c = await klien(peran, gudang)
        try:
            r = await c.get("/stok")
        finally:
            await c.aclose()
        assert r.status_code == 200, (peran, r.status_code)
        teks = r.text
        # Nama pemiliknya, DUA kali: kartu lot Gudang 1 dan kartu Tumpukan Gudang 2.
        assert teks.count("Pak Budi") >= 2, \
            f"{peran}: pemilik tak tergambar di kedua kartu ({teks.count('Pak Budi')}×)"
        assert "JAS-" in teks, f"{peran}: kode pesanannya tak tergambar"
        # Dan sebutannya menerangkan AKIBATNYA, bukan cuma namanya: "Pak Budi"
        # di pojok kartu tak memberi tahu siapa pun bahwa barangnya tak boleh
        # dijual — dan itu keputusan yang diambil dari layar ini.
        assert teks.count("bukan dijual") >= 2, peran


# ═══════ 8 · PELANGGAN BARU DIKETIK BEBAS — tetap jasa, bukan pemasok palsu ═══════
#
# Laporan lapangan 2 Oktober 2026 — pemilik melihat langsung di layar Stok:
# *"lot paling atas harusnya jasa. kenapa tidak terdeteksi sebagai jasa?"*
#
# Akarnya: pintu ketik-bebas Pos Timbang (sengaja dan sah — pelanggan baru
# memang bisa belum ada di cermin Kledo) membuat `pelanggan_id` tiketnya tetap
# NULL; satu-satunya penanda yang dulu dibaca produksi. Bagian 1–7 di atas TAK
# SATU PUN menguji bentuk ini — keduapuluhenam ujinya selalu memberi
# `pelanggan_id` yang sudah terisi (pelanggan dibuat lebih dulu lewat
# `_pelanggan()`), persis bentuk yang TIDAK pernah bermasalah. Lubangnya ada
# di bentuk yang tak satu pun uji sebelumnya mencoba.

async def test_pelanggan_baru_ketik_bebas_tetap_jadi_pesanan_bukan_pemasok(
        pg, pemakai):
    """⭐⭐ REPRODUKSI LANGSUNG laporan pemilik. Nama tiket sengaja SAMA.

    `jasa=True, pelanggan_id=None` — persis bentuk borang saat petugas
    mengetik nama baru alih-alih memilih dari daftar. Sebelum perbaikan ini,
    `adalah_jasa()` menjawab False di sini dan `create_purchase_batch_dari_
    timbang` membuat Supplier "Marnooo" dari `pihak_nama`.
    """
    from app.models import Supplier

    async with pg() as db:
        tid = await _tiket(db, kode="JTBEBAS1", berat=10_050, jasa=True,
                           pelanggan_id=None, pihak_nama="Marnooo")
        await db.commit()
    async with pg() as db:
        r = await _terima(db, tid, pemakai.id)
        jid = r.jasa.id

    assert r.supplier is None, "barang titipan tak boleh punya pemasok"
    assert r.batch.supplier_id is None
    assert r.batch.jasa_id == jid
    assert r.jasa.kode.startswith("JAS-")

    async with pg() as db:
        pemasok = (await db.execute(select(Supplier))).scalars().all()
        palsu = [s.nama_supplier for s in pemasok if "marno" in s.nama_supplier.lower()]
        assert palsu == [], f"pemasok palsu lahir dari nama pelanggan: {palsu}"
        # Dan pelanggannya SUNGGUH dibuat, dengan nama yang diketik.
        from app.models import Pelanggan
        pel = await db.get(Pelanggan, r.jasa.pelanggan_id)
        assert pel.nama_pelanggan == "Marnooo"


async def test_pelanggan_baru_ketik_bebas_pk_luar_tetap_jadi_pesanan(
        pg, admin, pabrik):
    """Jalur KEMBARANNYA — PK dari luar (bukan gabah). Fungsi yang berbeda,
    `adalah_jasa()` yang sama; kalau salah satu luput, bug ini kembali untuk
    separuh komoditas jasa."""
    from app.models import Supplier
    from app.penggilingan.gudang2.service import create_pk_purchase_dari_timbang

    async with pg() as db:
        tid = await _tiket(db, kode="JTBEBAS2", berat=5_000, jasa=True,
                           pelanggan_id=None, pihak_nama="Marnooo PK",
                           jenis="BERAS_PK")
        await db.commit()
    async with pg() as db:
        from app.models import User

        u = await db.get(User, admin.id)
        r = await create_pk_purchase_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, jenis_pk="KS")

    assert r.batch.supplier_id is None
    assert r.batch.jasa_id is not None

    async with pg() as db:
        pemasok = (await db.execute(select(Supplier))).scalars().all()
        palsu = [s.nama_supplier for s in pemasok
                if "marno" in s.nama_supplier.lower()]
        assert palsu == [], f"pemasok palsu lahir dari nama pelanggan: {palsu}"


async def test_kartu_antrean_menyebut_jasa_walau_pelanggan_belum_dibuat(
        pg, pemakai):
    """⚠ `nama_pihak()` punya cacat KEMBAR — diperiksa terpisah dari
    `adalah_jasa()`, sebab satu bisa dibetulkan tanpa yang lain.

    Sebelum perbaikan ini, kartu antrean untuk tiket bentuk ini jatuh ke
    cabang pemasok dan menampilkan nama telanjang TANPA tanda "JASA" — operator
    yang menerimanya tak diberi tahu sama sekali bahwa barang ini titipan.
    """
    from app.penggilingan.gudang1.services.timbang_link import (
        ambil_tiket, nama_pihak)

    async with pg() as db:
        tid = await _tiket(db, kode="JTBEBAS3", berat=9_000, jasa=True,
                           pelanggan_id=None, pihak_nama="Marnooo")
        await db.commit()

    async with pg() as db:
        t = await ambil_tiket(db, tid)
    assert nama_pihak(t) == "JASA · Marnooo", \
        "kartu antrean tak menyebut JASA untuk pelanggan baru ketik-bebas"
