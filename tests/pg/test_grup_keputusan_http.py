"""Sub-menu "Menunggu keputusan" lewat jalur HTTP sungguhan.

Keputusan pemilik 2 Oktober 2026: *"lakukan yang sama ke menunggu
keputusan"* — diperjelas *"buat sub menu juga sesuai kategori"*. Grouping
murninya sudah diuji atas angka telanjang di `tests/test_grup_keputusan.py`
(Σ kategori, mutu dikecualikan, syarat dua kategori, kategori == blok
halaman) — di sini yang dibuktikan jalur SUNGGUHANNYA: `/keputusan`
dirender lewat HTTP atas data real (`permintaan_pk.minta()`, fixture yang
sama dipakai `tests/pg/test_permintaan_pk.py`), bukan `Baris` buatan tangan.
"""
from __future__ import annotations

import httpx
import pytest

from tests.pg.test_permintaan_pk import _minta, pabrik  # noqa: F401 — fixture

pytestmark = pytest.mark.asyncio


async def _klien(pg, uid) -> httpx.AsyncClient:
    from app.main import app
    from app.models import User
    from app.web import csrf, security

    async with pg() as db:
        u = await db.get(User, uid)
        tok = security.buat_token_untuk_user(u) if hasattr(
            security, "buat_token_untuk_user") else None
    if tok is None:
        # Jalur yang dipakai seluruh uji HTTP lain di repo ini: akun login
        # sungguhan, bukan menembus token langsung dari `User`.
        from app.models import ProduksiAkun
        from hmu_identitas import sandi as S
        from hmu_identitas.model import mode_bawaan

        async with pg() as db:
            u = await db.get(User, uid)
            a = ProduksiAkun(user_id=u.id, username=f"gk{u.id}",
                             password_hash=S.hash_sandi("rahasia123"),
                             status="aktif", mode_perangkat=mode_bawaan(u.role))
            db.add(a)
            await db.commit()
            tok = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji", follow_redirects=True)
    c.cookies.set(security.NAMA_COOKIE, tok)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    return c


async def test_permintaan_tergambar_dan_kategori_lain_kosong(pg, pabrik):
    """⭐ REPRODUKSI SUNGGUHAN: satu permintaan PK nyata, dibaca lewat
    `/keputusan` DAN `/keputusan?kategori=betulkan_bobot_giling` oleh Admin
    yang sungguh login."""
    await _minta(pg, pabrik["op2"])
    c = await _klien(pg, pabrik["adm"])
    try:
        semua = await c.get("/keputusan")
        lain = await c.get("/keputusan?kategori=betulkan_bobot_giling")
        ngawur = await c.get("/keputusan?kategori=tidak-ada")
    finally:
        await c.aclose()

    assert semua.status_code == 200
    assert pabrik["lot"] in semua.text
    # `<div class="saring">` — penanda blok pil ITU SENDIRI di halaman ini.
    # `<a class="pil` SAJA pernah dipakai dan ternyata longgar: kartu
    # "Setujui/Tolak permintaan" sungguhan merender `class="pilihan__satu"`
    # sebagai `<a>`, yang diawali huruf sama ("pil"). `keputusan.html` tak
    # punya fitur lain yang memakai `.saring` (beda dengan `aksi.html`, yang
    # memakainya untuk kotak cari) — jadi di SINI penandanya aman dipakai.
    assert '<div class="saring">' not in semua.text

    assert lain.status_code == 200
    assert "Tidak ada pekerjaan perlu tindakan" in lain.text
    assert pabrik["lot"] not in lain.text

    # Alamat kategori yang tak dikenal diperlakukan seperti "semua" — bukan
    # galat, sebab ia bisa datang dari tautan lama atau salah ketik.
    assert ngawur.status_code == 200
    assert pabrik["lot"] in ngawur.text


async def test_dua_kategori_lahir_dari_satu_lot_tetap_terpisah(pg, pabrik):
    """⭐ INTI PERMINTAANNYA, via HTTP: "Permintaan lot PK dari Gudang 2"
    DAN "Kiriman PK menunggu ditutup" adalah DUA kategori — bukan satu
    golongan "permintaan" tergabung — begitu permintaan yang sama berjalan
    sampai tahap kirim."""
    from sqlalchemy import select

    from app.models import User
    from app.services.permintaan_pk import kirim, setujui

    pid = (await _minta(pg, pabrik["op2"])).id
    async with pg() as db:
        adm = await db.get(User, pabrik["adm"])
        await setujui(db, user=adm, permintaan_id=pid, tujuan="A", berat=1_000)
    async with pg() as db:
        # "Kiriman PK menunggu ditutup" muncul begitu statusnya DIKIRIM —
        # disetujui saja belum cukup (kartunya masih "menunggu Gudang 1
        # memuat", bukan "menunggu ditutup Admin").
        op1 = await db.get(User, pabrik["op1"])
        await kirim(db, user=op1, permintaan_id=pid, berat=1_000)

    c = await _klien(pg, pabrik["adm"])
    try:
        semua = await c.get("/keputusan")
        satu = await c.get("/keputusan?kategori=tutup_permintaan_pk")
    finally:
        await c.aclose()

    assert semua.status_code == 200
    assert "Kiriman PK menunggu ditutup" in semua.text
    assert satu.status_code == 200
    assert pabrik["lot"] in satu.text


async def test_submenu_keputusan_di_laci_sesuai_isi_sungguhan(pg, pabrik):
    """`Berjalan.submenu()["keputusan"]` dihitung dari jalur AGREGASI penuh
    (`svc.untuk`), bukan dipanggil terisolasi — membuktikan ia benar-benar
    terhubung ke `can_see_financials` dan pengumpulan `untuk_gudang2`/
    `untuk_staff` yang sesungguhnya dipakai server."""
    from app.models import User
    from app.services import berjalan as svc

    await _minta(pg, pabrik["op2"])
    async with pg() as db:
        adm = await db.get(User, pabrik["adm"])
        b = await svc.untuk(db, adm)

    # Satu kategori saja ("acc_permintaan_pk") → sub-menu TAK ditawarkan di
    # laci, persis seperti Antrian tunggu saat cuma satu grup berisi.
    assert "keputusan" not in b.submenu()
    assert b.jumlah_keputusan == 1


# ═══ CELAH LAPANGAN 2 Oktober 2026: "verifikasi_keluar" hilang dari K.JENIS ═══

async def test_verifikasi_muatan_tidak_menambah_kategori_keputusan(
        pg, pabrik):
    """Pengiriman diverifikasi di Barang Keluar; kategori meja hanya pekerjaan lain."""
    from datetime import date

    from sqlalchemy import select

    from app.database import now_local
    from app.models import FinishedGoodsStock, PkPurchaseBatch, Silo, Supplier, User, Warehouse
    from app.penggilingan.gudang2.models import (PolishingOutputLog,
                                                 PolishingProcess,
                                                 PolishingSiloUsage)
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services import barang_keluar as bk
    from app.services.seed import seed_master
    from app.services import berjalan as svc

    # ── Satu "Permintaan lot PK dari Gudang 2" ──
    await _minta(pg, pabrik["op2"])

    # ── Satu "Verifikasi Muatan" — dibangun persis seperti test_barang_
    # keluar.py: packing barang jadi → perintah muat → dimuat operator. ──
    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        silo = Silo(nama_silo="Silo BK", warehouse_id=g2.id)
        s = Supplier(nama_supplier="UD Sumber BK")
        db.add_all([silo, s])
        await db.flush()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-BKX-01", supplier_id=s.id, berat_total_kg=20_000,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=pabrik["op1"], status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        p = PolishingProcess(kode_proses="POL-BKX-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=pabrik["op1"])
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo.id,
                                  berat_awal_kg=20_000, berat_masuk_kg=0,
                                  berat_akhir_kg=0, berat_terpakai_kg=20_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="medium",
                                  berat_kg=10_000, waktu_update=now_local(),
                                  input_by=pabrik["op1"]))
        await db.commit()
    async with pg() as db:
        u = await db.get(User, pabrik["op1"])
        await catat_packing(db, user=u, kode_pol="POL-BKX-01",
                            kategori="beras_putih", grade="medium",
                            material_kode="biasa", ukuran=25, jumlah_karung=100)
    async with pg() as db:
        from app.models import Pelanggan
        sku_id, std_id = (await db.execute(select(
            FinishedGoodsStock.product_sku_id,
            FinishedGoodsStock.rice_quality_standard_id).limit(1))).first()
        adm = await db.get(User, pabrik["adm"])
        klien = Pelanggan(nama_pelanggan="Toko Uji")
        db.add(klien)
        await db.flush()
        r = await bk.buat_perintah(
            db, user=adm,
            baris=[bk.BarisPerintah(tipe="finished_goods", sku_id=sku_id,
                                    std_id=std_id, jumlah_karung=50)],
            pelanggan_id=klien.id, no_polisi="B 9 BK")
    async with pg() as db:
        u = await db.get(User, pabrik["op1"])
        await bk.muat_semua(db, user=u, rec_id=r.rec.id)

    # Pengiriman tidak menambah kategori atau lencana Menunggu Keputusan.
    async with pg() as db:
        adm = await db.get(User, pabrik["adm"])
        b = await svc.untuk(db, adm)
    n = b.jumlah_grup_keputusan()
    assert n["acc_permintaan_pk"] == 1
    assert "verifikasi_keluar" not in n
    assert n["lain"] == 0, "salah satunya masih jatuh ke keranjang Lainnya"
    assert r.rec.kode not in {x.kode for x in b.meja}
    assert "keputusan" not in b.submenu()

    c = await _klien(pg, pabrik["adm"])
    try:
        r2 = await c.get("/keputusan")
    finally:
        await c.aclose()
    assert "Muatan menunggu diverifikasi" not in r2.text
    assert "buka=acc_permintaan_pk" in r2.text
    assert "Keputusan lain" not in r2.text, \
        "salah satunya masih jatuh ke jaring, bukan bloknya sendiri"
