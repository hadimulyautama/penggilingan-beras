"""Gabah kering dikemas & ditimbang — pesan kerja 7 Oktober 2026 butir 6.

PESAN-KERJA-12 bagian 3 (karung gabah di `finished_goods_stock`, kategori
`gabah_kering`) DICABUT SELURUHNYA oleh 12A: gabah tak punya ukuran karung
baku. Jalan keluarnya meniru `pk_langsung` — satu angka bobot global, tanpa
SKU, tanpa karung wajib. Ujinya karena itu TIDAK menyentuh `stok_produk()`
maupun `finished_goods_stock` sama sekali — gabah tetap BAHAN.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg, pemakai, pemasok):
    """Gudang 1 dengan silo A & B, superadmin, satu pesanan jasa (Bu Sri)."""
    from sqlalchemy import select

    from app.models import Jasa, Pelanggan, Silo, User, Warehouse

    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
            db.add(g1)
            await db.flush()
        # `barang_jasa()` (picker pengambilan jasa) ikut memeriksa silo PK
        # Gudang 2 pemilik pesanan (pesan kerja 11 butir 4) — tanpa gudangnya
        # ADA (walau kosong), fungsi itu melempar `Gudang2Error` murni karena
        # Gudang 2 belum pernah disebut di uji ini, bukan karena ada yang
        # salah dengan gabah kering.
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
            db.add(g2)
            await db.flush()
        silo = {}
        for huruf in ("A", "B"):
            s = (await db.execute(select(Silo).where(
                Silo.nama_silo == f"Silo {huruf}",
                Silo.warehouse_id == g1.id))).scalars().first()
            if s is None:
                s = Silo(nama_silo=f"Silo {huruf}", warehouse_id=g1.id, status="kosong")
                db.add(s)
                await db.flush()
            silo[huruf] = s.id
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g1.id
        u.role = "superadmin"
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(pel)
        await db.flush()
        jasa = Jasa(kode="JAS-2610-020", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.commit()
        return {"g1": g1.id, "silo": silo, "user": u.id, "pemasok": pemasok.id,
                "jasa_id": jasa.id, "pelanggan_id": pel.id}


async def _isi_silo_langsung(pg, pabrik, *, huruf: str, kode: str, kg: float,
                             jasa_id: int | None = None) -> int:
    """Tulis PurchaseBatch (langsung_kering) + SiloStorage langsung — pola
    yang sudah dipakai `test_jalur_salah.py`. → id baris silo-nya."""
    from app.database import now_local
    from app.models import PurchaseBatch, SiloStorage, User

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        b = PurchaseBatch(
            kode_batch=kode, supplier_id=pabrik["pemasok"] if jasa_id is None else None,
            jasa_id=jasa_id, berat_total_kg=kg, kondisi_gabah="kering",
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, flag_unverified=False, sumber_berat="timbangan",
            status_batch="di_silo")
        db.add(b)
        await db.flush()
        row = SiloStorage(silo_id=pabrik["silo"][huruf], purchase_batch_id=b.id,
                          tipe_masuk="langsung_kering", tanggal_masuk=now_local(),
                          input_by=u.id, status="terisi", jasa_id=jasa_id)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _keluarkan(pg, pabrik, *, silo_storage_id: int, berat_kg: float,
                     jumlah_karung: int | None = None):
    from app.models import User
    from app.penggilingan.gudang1.services.gabah_kering import keluarkan_untuk_kemasan

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        return await keluarkan_untuk_kemasan(
            db, user=u, silo_storage_id=silo_storage_id, berat_kg=berat_kg,
            jumlah_karung=jumlah_karung)


# ───────────────── Keluarkan dari silo: stok berkurang tepat ─────────────────

async def test_keluarkan_mengurangi_stok_silo_tepat_sejumlah_dikemas(pg, pabrik):
    from app.penggilingan.gudang1.services.silo import _silo_content_kg

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-01", kg=10_000)
    r = await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=4_930,
                         jumlah_karung=100)
    assert r.lot.berat_timbang_kg == 4_930      # bobot TIMBANG, bukan karung × ukuran
    assert r.lot.jumlah_karung == 100
    assert r.sisa_silo_kg == 5_070

    async with pg() as db:
        assert await _silo_content_kg(db, pabrik["silo"]["A"]) == 5_070


async def test_sisa_silo_masih_bisa_digiling(pg, pabrik):
    """Sebagian dikemas, sisanya tetap bisa jadi bahan giling — pesan 12
    bagian 5: "sebagian isi silo bisa dikemas sementara sisanya digiling".

    Dibuktikan lewat `isi_silo()` (yang dipakai borang "Mulai giling" untuk
    menampilkan bahan yang tersedia) — bukan cuma `_row_bobot` langsung,
    sebab `isi_silo` punya jalur hitungnya sendiri yang pernah berselisih
    dari `_row_bobot` sebelum keduanya disatukan (lihat catatan di sana)."""
    from app.penggilingan.gudang1.services.silo import isi_silo

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-02", kg=10_000)
    await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=4_000)

    async with pg() as db:
        rinci = await isi_silo(db, pabrik["silo"]["A"])
    assert len(rinci) == 1 and rinci[0].kg == 6_000, \
        "sisa yang belum dikemas (6.000 kg) masih harus tampil, siap digiling"


# ───────────────────── Pagar fisika: kering <= basah masuk ─────────────────────

async def test_keluarkan_melebihi_sisa_ditolak(pg, pabrik):
    from app.penggilingan.gudang1.services.gabah_kering import GabahKeringError

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-03", kg=10_000)
    with pytest.raises(GabahKeringError) as e:
        await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=86_000)
    assert "tinggal" in str(e.value)


# ───────────────────── Dibongkar kembali ke silo ─────────────────────

async def test_bongkar_ke_silo_mengkreditkan_bobot_timbang_bukan_batch(pg, pabrik):
    """Pesan 12A butir 4b — jebakan terbesar: silo HARUS dikreditkan bobot
    TIMBANG (pasca-pengeringan), bukan bobot batch asal (pra-pengeringan).
    Dibuktikan dengan dua angka yang BERBEDA jauh."""
    from app.models import User
    from app.penggilingan.gudang1.services.silo import masuk_silo
    from app.penggilingan.gudang1.services.gabah_kering import saldo_gabah_kering

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-04", kg=10_000)
    r = await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=8_600)  # susut 14%

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        hasil = await masuk_silo(db, user=u, nama_silo="B", kode_lot=None,
                                 kode_batch=None, kode_gkr=r.lot.kode_lot)
    assert hasil.kg_baris == 8_600, "silo B harus dikreditkan BOBOT TIMBANG (8.600), bukan bobot batch asal (10.000)"

    async with pg() as db:
        from app.penggilingan.gudang1.services.silo import _silo_content_kg
        assert await _silo_content_kg(db, pabrik["silo"]["B"]) == 8_600
        assert await saldo_gabah_kering(db, r.lot.id) == 0


async def test_dua_pemilik_berbeda_dibongkar_ke_silo_sama_ditolak(pg, pabrik):
    from app.models import User
    from app.penggilingan.gudang1.services.silo import SiloError, masuk_silo

    row_a = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-05", kg=5_000,
                                     jasa_id=pabrik["jasa_id"])
    r_a = await _keluarkan(pg, pabrik, silo_storage_id=row_a, berat_kg=4_500)

    # Silo B sudah berisi barang PABRIK — membongkar lot JASA ke sana ditolak.
    await _isi_silo_langsung(pg, pabrik, huruf="B", kode="GB-GKR-06", kg=3_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        with pytest.raises(SiloError) as e:
            await masuk_silo(db, user=u, nama_silo="B", kode_lot=None,
                             kode_batch=None, kode_gkr=r_a.lot.kode_lot)
    assert "digabung" in str(e.value).lower() or "pemilik" in str(e.value).lower() \
        or "pak" in str(e.value).lower() or "sri" in str(e.value).lower() \
        or "❌" in str(e.value)


# ───────────────────── Timbang ulang (pesan 12B) ─────────────────────

async def test_timbang_ulang_mengganti_bukan_menjumlah(pg, pabrik):
    from app.penggilingan.gudang1.services.gabah_kering import (
        saldo_gabah_kering, timbang_ulang)
    from app.models import User

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-07", kg=10_000)
    r = await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=8_600)  # W1

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        lot = await timbang_ulang(db, user=u, kode_lot=r.lot.kode_lot, berat_kg=8_200)  # W2

    assert lot.berat_timbang_kg == 8_200, "DIGANTI, bukan 8.600+8.200"
    async with pg() as db:
        assert await saldo_gabah_kering(db, r.lot.id) == 8_200


async def test_timbang_ulang_lebih_besar_ditolak(pg, pabrik):
    from app.penggilingan.gudang1.services.gabah_kering import (
        GabahKeringError, timbang_ulang)
    from app.models import User

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-08", kg=10_000)
    r = await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=8_600)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        with pytest.raises(GabahKeringError) as e:
            await timbang_ulang(db, user=u, kode_lot=r.lot.kode_lot, berat_kg=8_900)
    assert "tak pernah menambah bobot" in str(e.value) or "melebihi" in str(e.value)


async def test_bongkar_sesudah_timbang_ulang_memakai_w2(pg, pabrik):
    from app.models import User
    from app.penggilingan.gudang1.services.gabah_kering import timbang_ulang
    from app.penggilingan.gudang1.services.silo import masuk_silo

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-09", kg=10_000)
    r = await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=8_600)
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await timbang_ulang(db, user=u, kode_lot=r.lot.kode_lot, berat_kg=8_200)
        hasil = await masuk_silo(db, user=u, nama_silo="B", kode_lot=None,
                                 kode_batch=None, kode_gkr=r.lot.kode_lot)
    assert hasil.kg_baris == 8_200


# ───────────────────── SisaJasa — tidak dihitung dua kali ─────────────────────

async def test_gabah_kering_tak_terbaca_sisa_gabah_dan_tak_dobel(pg, pabrik):
    from app.services.jasa import boleh_ditutup, sisa_jasa

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-10", kg=7_000,
                                      jasa_id=pabrik["jasa_id"])
    # Seluruh isi silo dikeluarkan — supaya `silo_kg` turun tepat ke NOL dan
    # bisa diadu langsung dengan "tak boleh dobel", bukan cuma dikurangi
    # sebagian (yang pasti tak nol bahkan tanpa cacat apa pun).
    await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=7_000)

    async with pg() as db:
        sisa = await sisa_jasa(db, pabrik["jasa_id"])
        assert sisa.gabah_kg == 0, "gabah yang sudah dikemas BUKAN 'belum masuk mesin'"
        assert sisa.silo_kg == 0, "silo sudah berkurang (dikemas_kg) — tak boleh dobel"
        assert sisa.gabah_kering_kg == 7_000
        boleh, sebab = await boleh_ditutup(db, pabrik["jasa_id"])
        assert not boleh and "gabah kering" in sebab.lower()


async def test_pesanan_boleh_ditutup_sesudah_gabah_kering_terangkut(pg, pabrik):
    """Pesanan jasa yang berakhir di gabah kering: bisa diambil pemiliknya,
    dan sesudah terangkut `boleh_ditutup` jadi True."""
    from app.models import User
    from app.services import barang_keluar as bk
    from app.services.jasa import boleh_ditutup
    from app.web.aksi_inventory import barang_jasa

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-11", kg=5_000,
                                      jasa_id=pabrik["jasa_id"])
    # Seluruh isi silo dikeluarkan — sisa yang tertinggal di silo akan
    # (BENAR) menolak penutupan, dan itu bukan yang diuji di sini.
    r = await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=5_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
    opsi = {o["value"] for o in await barang_jasa(induk=str(pabrik["pelanggan_id"]), user=u)}
    assert f"gk:{r.lot.kode_lot}@{pabrik['jasa_id']}" in opsi

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        rec = await bk.buat_perintah(
            db, user=u, jasa_id=pabrik["jasa_id"],
            baris=[bk.BarisPerintah(tipe="gabah_langsung",
                                    gabah_kering_lot_id=r.lot.id, berat_kg=5_000)])
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await bk.muat_semua(db, user=u, rec_id=rec.rec.id)

    async with pg() as db:
        boleh, sebab = await boleh_ditutup(db, pabrik["jasa_id"])
        assert boleh, sebab


async def test_pesanan_lain_tak_bisa_mengambil_gabah_kering_pesanan_ini(pg, pabrik):
    from app.models import Jasa, Pelanggan, User
    from app.services import barang_keluar as bk

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-12", kg=3_000,
                                      jasa_id=pabrik["jasa_id"])
    r = await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=2_800)

    async with pg() as db:
        pel2 = Pelanggan(nama_pelanggan="Pak Budi")
        db.add(pel2)
        await db.flush()
        jasa2 = Jasa(kode="JAS-2610-021", pelanggan_id=pel2.id, status="berjalan")
        db.add(jasa2)
        await db.commit()
        jasa2_id = jasa2.id

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.buat_perintah(
                db, user=u, jasa_id=jasa2_id,
                baris=[bk.BarisPerintah(tipe="gabah_langsung",
                                        gabah_kering_lot_id=r.lot.id, berat_kg=1_000)])
    assert "bukan barang pesanan ini" in str(e.value)


# ───────────────── Tak pernah tercampur stok produk / beras ─────────────────

async def test_gabah_kering_tak_tersentuh_stok_produk(pg, pabrik):
    """TIDAK ADA baris gabah di Stok Produk — ia keluar lewat jenis barang
    Gudang 1 sendiri, tak pernah lewat `finished_goods_stock`."""
    from app.services.stok import stok_produk

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-13", kg=4_000)
    await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=3_500)

    async with pg() as db:
        kartu = await stok_produk(db)
    assert kartu == [] or all("gabah" not in (k.jenis or "").lower() for k in kartu)


# ───── Sisa silo sesudah dikemas: giling memakai bahan yang BENAR ─────

async def test_giling_sisa_silo_sesudah_dikemas_memakai_bobot_yang_benar(pg, pabrik):
    """`start_milling` (dan poller `resinkron_bahan_berjalan`) WAJIB membaca
    sisa silo lewat `_row_bobot` yang sama dengan `keluarkan_untuk_kemasan` —
    dulu `milling._storage_bobot` menyalin rumusnya sendiri TANPA mengurangi
    `dikemas_kg`, jadi silo yang sebagian isinya sudah dikeluarkan untuk
    dikemas tetap mengkreditkan bobot PENUH ke proses giling berikutnya:
    `berat_gabah_masuk_kg` menggelembung, rendemen jatuh — kelas kerusakan
    yang sama dengan nota-vs-timbangan 25 September."""
    from app.models import User
    from app.penggilingan.gudang1.services.milling import start_milling

    row_id = await _isi_silo_langsung(pg, pabrik, huruf="A", kode="GB-GKR-14", kg=10_000)
    await _keluarkan(pg, pabrik, silo_storage_id=row_id, berat_kg=6_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await start_milling(db, user=u, nama_silo="A")

    assert r.berat_masuk == 4_000, (
        f"bahan masuk giling harus 4.000 kg (10.000 − 6.000 dikemas), "
        f"bukan {r.berat_masuk} kg"
    )
