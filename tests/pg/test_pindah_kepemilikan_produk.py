"""Pindah kepemilikan — titipan jadi milik pabrik (6 Oktober 2026).

Keputusan pemilik, halaman "Produk Jasa": barang atau hasil samping
pelanggan "bisa jadi milik kita ataupun kita beli" — dan koreksi susulan
("admin should typr a kg/karung amount for a partial transter") menolak
pindah "semua atau tidak sama sekali": admin mengetik jumlahnya sendiri,
FIFO, baris dipecah bila jumlahnya jatuh di tengah satu baris.

Berkas ini membuktikan di Postgres sungguhan: pemindahan AMAN walau sebagian
sisa pesanan sudah diambil pelanggan (`outgoing_records`), pagar menolak
memindahkan lebih daripada sisa, dan — pelajaran dari koreksi lapangan
"pemisahannya bukan per proses, tapi per pelanggan" — broken curah milik
PELANGGAN (bisa beberapa pesanan) dijawab & dipindah sebagai SATU angka
gabungan, dengan picker katalog umum mengelompokkannya dengan cara yang
SAMA supaya nilai tombol selalu cocok dengan satu pilihan picker.
"""
from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def titipan(pg, pemakai):
    """Bu Sri: dua pesanan.

    Pesanan 1 (`jasa1`): 5.000 kg medium disosoh, 20 karung (500 kg) sudah
    dipacking, dan 500 kg broken sudah dicatat curah (dua baris: 300 + 200,
    supaya transfer FIFO menyentuh lebih dari satu baris).

    Pesanan 2 (`jasa2`): 100 kg broken curah sendiri — dipakai membuktikan
    sisa broken curah Bu Sri (dua pesanan) dijawab sebagai SATU angka
    gabungan, bukan dijumlah belakangan oleh pemanggil.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import ByproductStock, Jasa, Pelanggan, Silo, User, Warehouse
    from app.penggilingan.gudang2.models import (PolishingOutputLog, PolishingProcess,
                                                  PolishingSiloUsage)
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.seed import seed_master
    from app.services.stok import barang_jadi_g2

    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        silo = (await db.execute(select(Silo).where(
            Silo.warehouse_id == g2.id))).scalars().first()
        if silo is None:
            silo = Silo(nama_silo="Silo A", warehouse_id=g2.id)
            db.add(silo)
            await db.flush()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(pel)
        await db.flush()
        jasa1 = Jasa(kode="JAS-2610-001", pelanggan_id=pel.id, status="berjalan")
        jasa2 = Jasa(kode="JAS-2610-002", pelanggan_id=pel.id, status="berjalan")
        db.add_all([jasa1, jasa2])
        await db.flush()

        p1 = PolishingProcess(kode_proses="POL-UJIT-01", status="selesai",
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=u.id, jasa_id=jasa1.id)
        # `jasa_ids_per_pelanggan_dengan_hasil()` menemukan pesanan lewat
        # `PolishingProcess.jasa_id` — pesanan kedua Bu Sri WAJIB punya
        # prosesnya SENDIRI, bukan menumpang `source_id=p1.id`, kalau tidak
        # ia tak pernah terhitung sebagai "pesanan yang pernah menghasilkan
        # sosoh" dan hilang dari grup gabungannya.
        p2 = PolishingProcess(kode_proses="POL-UJIT-02", status="selesai",
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=u.id, jasa_id=jasa2.id)
        db.add_all([p1, p2])
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p1.id, silo_id=silo.id,
                                  berat_awal_kg=5_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=5_000))
        db.add(PolishingOutputLog(polishing_process_id=p1.id, jenis="medium",
                                  berat_kg=5_000, waktu_update=now_local(),
                                  input_by=u.id))
        db.add(PolishingSiloUsage(polishing_process_id=p2.id, silo_id=silo.id,
                                  berat_awal_kg=1_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=1_000))
        db.add(PolishingOutputLog(polishing_process_id=p2.id, jenis="broken",
                                  berat_kg=100, waktu_update=now_local(),
                                  input_by=u.id))
        await db.flush()

        kini = now_local()
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=p1.id, berat_kg=300, tanggal=kini.date(),
                              waktu=kini, input_by=u.id, jasa_id=jasa1.id))
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=p1.id, berat_kg=200, tanggal=kini.date(),
                              waktu=kini, input_by=u.id, jasa_id=jasa1.id))
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=p2.id, berat_kg=100, tanggal=kini.date(),
                              waktu=kini, input_by=u.id, jasa_id=jasa2.id))
        await db.commit()

        await catat_packing(db, user=u, kode_pol="POL-UJIT-01", kategori="beras_putih",
                            grade="medium", material_kode="biasa", ukuran=25,
                            jumlah_karung=20)
        bj = await barang_jadi_g2(db)

    kartu = next(k for k in bj.produk if k["jasa_id"] == jasa1.id)
    return {"user": pemakai.id, "pelanggan_id": pel.id,
            "jasa1": jasa1.id, "jasa2": jasa2.id,
            "sku_id": kartu["sku_id"], "std_id": kartu["std_id"]}


# ═══════════════════ Barang jadi (karung) — FIFO & pagar ═══════════════════

async def test_pindah_barang_jadi_sebagian_memecah_baris(pg, titipan):
    """20 karung milik jasa1; pindah 5 — sisanya 15 tetap jasa1, 5 jadi
    pabrik, dan beratnya persis proporsional (25 kg/karung)."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import (
        hitung_stok_finished_goods, pindah_kepemilikan_barang_jadi)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        berat = await pindah_kepemilikan_barang_jadi(
            db, user=u, sku_id=titipan["sku_id"], standard_id=titipan["std_id"],
            jasa_id=titipan["jasa1"], karung=5)
        assert berat == pytest.approx(125.0)

        sisa_jasa = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"], jasa_id=titipan["jasa1"])
        sisa_pabrik = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"])
    assert sisa_jasa == {"karung": 15, "kg": pytest.approx(375.0)}
    assert sisa_pabrik == {"karung": 5, "kg": pytest.approx(125.0)}


async def test_pindah_barang_jadi_menolak_lebih_dari_sisa(pg, titipan):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import (
        InventoryError, pindah_kepemilikan_barang_jadi)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        with pytest.raises(InventoryError, match="tinggal 20 karung"):
            await pindah_kepemilikan_barang_jadi(
                db, user=u, sku_id=titipan["sku_id"], standard_id=titipan["std_id"],
                jasa_id=titipan["jasa1"], karung=21)


async def test_pindah_barang_jadi_aman_walau_sebagian_sudah_diambil(pg, titipan):
    """Pelanggan sudah mengambil 12 dari 20 karung (perintah barang keluar
    sungguhan, bukan simulasi kosong) — sisa 8, dan memindahkan SELURUH sisa
    itu tak boleh mengambil lebih atau kurang daripada 8 karung persis,
    walau baris `finished_goods_stock` yang dipilih FIFO sudah tersentuh
    pengambilan itu."""
    from datetime import date as _date

    from app.database import now_local
    from app.models import OutgoingItem, OutgoingRecord, User
    from app.penggilingan.inventory.finished_goods import (
        hitung_stok_finished_goods, pindah_kepemilikan_barang_jadi)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        kini = now_local()
        rec = OutgoingRecord(kode="OUT-UJIT-01", jasa_id=titipan["jasa1"],
                             tanggal=kini.date(), waktu=kini, input_by=u.id,
                             status="selesai")
        db.add(rec)
        await db.flush()
        db.add(OutgoingItem(outgoing_record_id=rec.id, item_type="finished_goods",
                            product_sku_id=titipan["sku_id"],
                            rice_quality_standard_id=titipan["std_id"],
                            jumlah_karung=12, berat_kg=300,
                            jasa_id=titipan["jasa1"]))
        await db.commit()

        sisa = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"], jasa_id=titipan["jasa1"])
        assert sisa == {"karung": 8, "kg": pytest.approx(200.0)}

        berat = await pindah_kepemilikan_barang_jadi(
            db, user=u, sku_id=titipan["sku_id"], standard_id=titipan["std_id"],
            jasa_id=titipan["jasa1"], karung=8)
        assert berat == pytest.approx(200.0)

        sisa_jasa = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"], jasa_id=titipan["jasa1"])
        sisa_pabrik = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"])
    assert sisa_jasa == {"karung": 0, "kg": pytest.approx(0.0)}
    assert sisa_pabrik == {"karung": 8, "kg": pytest.approx(200.0)}


# ═══════════════════ Broken curah — gabungan per pelanggan ═══════════════════

async def test_hitung_broken_curah_daftar_jasa_id_menjumlah_gabungan(pg, titipan):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah

    async with pg() as db:
        satu = await hitung_stok_broken_curah(db, jasa_id=titipan["jasa1"])
        dua = await hitung_stok_broken_curah(db, jasa_id=titipan["jasa2"])
        gabungan = await hitung_stok_broken_curah(
            db, jasa_id=[titipan["jasa1"], titipan["jasa2"]])
    assert satu == pytest.approx(500.0)
    assert dua == pytest.approx(100.0)
    assert gabungan == pytest.approx(satu + dua)


async def test_pindah_broken_curah_gabungan_dua_pesanan_memecah_baris(pg, titipan):
    """Sisa gabungan Bu Sri = 500 (jasa1, dua baris) + 100 (jasa2) = 600.
    Memindahkan 550 kg wajib menghabiskan SELURUH baris jasa1 (300+200)
    dan memecah baris jasa2 (100 → 50 pabrik + 50 tetap jasa2)."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import (
        hitung_stok_broken_curah, pindah_kepemilikan_broken_curah)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        berat = await pindah_kepemilikan_broken_curah(
            db, user=u, jasa_id=[titipan["jasa1"], titipan["jasa2"]], berat_kg=550)
        assert berat == pytest.approx(550.0)

        gabungan = await hitung_stok_broken_curah(
            db, jasa_id=[titipan["jasa1"], titipan["jasa2"]])
        sisa_jasa2 = await hitung_stok_broken_curah(db, jasa_id=titipan["jasa2"])
        sisa_pabrik = await hitung_stok_broken_curah(db)
    assert gabungan == pytest.approx(50.0)
    assert sisa_jasa2 == pytest.approx(50.0), \
        "baris jasa2 wajib terpecah, bukan jasa1 dipaksa menyumbang lebih"
    assert sisa_pabrik == pytest.approx(550.0)


async def test_pindah_broken_curah_menolak_lebih_dari_gabungan(pg, titipan):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import (
        InventoryError, pindah_kepemilikan_broken_curah)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        with pytest.raises(InventoryError, match="tinggal 600"):
            await pindah_kepemilikan_broken_curah(
                db, user=u, jasa_id=[titipan["jasa1"], titipan["jasa2"]],
                berat_kg=601)


# ═══════════════════ Picker & rute — nilainya wajib cocok ═══════════════════

async def test_picker_mengelompokkan_broken_per_pelanggan_bukan_pesanan(pg, titipan):
    """`produk_jasa_tersedia` wajib menawarkan broken curah Bu Sri sebagai
    SATU baris gabungan dua pesanan — bukan dua baris per pesanan — sebab
    tombol per-kartu di `/stok-produk-jasa` membawa SELURUH `jasa_ids`
    pelanggan itu sekaligus (lihat `layar_produk.halaman_stok_produk_jasa`).
    Nilai yang tak cocok berarti medan "item" di borang gagal terisi
    otomatis tanpa satu pun galat (`aksi.js` mencocokkan apa adanya)."""
    from types import SimpleNamespace

    from app.web.aksi_inventory import produk_jasa_tersedia

    admin = SimpleNamespace(id=titipan["user"], role="admin", nama="Uji")
    daftar = await produk_jasa_tersedia(user=admin)
    baris_cr = [b for b in daftar if b["value"].startswith("cr:broken|")]
    assert len(baris_cr) == 1, "dua pesanan satu pelanggan harus satu baris"
    nilai = baris_cr[0]["value"]
    ids = {int(x) for x in nilai.split("|", 1)[1].split(",")}
    assert ids == {titipan["jasa1"], titipan["jasa2"]}
    assert "600" in baris_cr[0]["label"]
    assert "Bu Sri" in baris_cr[0]["label"]


async def _klien(pg, *, peran: str = "admin") -> "httpx.AsyncClient":
    """Klien HTTP berlogin — sebangun `_klien` di `test_stok_produk_jasa.py`."""
    import httpx

    from app.main import app
    from app.models import ProduksiAkun, User
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        u = User(nama=f"Uji {peran}", role=peran, status="aktif")
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username=f"pkp{u.id}",
                         password_hash=S.hash_sandi("rahasia123"),
                         status="aktif", mode_perangkat=mode_bawaan(peran))
        db.add(a)
        await db.commit()
        tok = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji", follow_redirects=True)
    t = csrf.terbitkan_baru()
    c.cookies.set(security.NAMA_COOKIE, tok)
    c.cookies.set(csrf.NAMA_COOKIE, t)
    c.headers[csrf.NAMA_HEADER] = t
    return c


async def test_rute_transfer_gerbang_admin_dan_nilai_gabungan_via_http(pg, titipan):
    """Operator ditolak (`can_see_financials`), Admin berhasil memindahkan
    broken curah lewat nilai GABUNGAN (`cr:broken|id1,id2`) persis seperti
    yang dikirim tombol per-kartu halaman `/stok-produk-jasa`."""
    nilai = f"cr:broken|{titipan['jasa1']},{titipan['jasa2']}"

    c = await _klien(pg, peran="operator")
    try:
        r = await c.post("/api/actions/pindah-kepemilikan-produk",
                         json={"item": nilai, "jumlah": 550})
    finally:
        await c.aclose()
    assert r.status_code == 403

    c = await _klien(pg, peran="admin")
    try:
        r = await c.post("/api/actions/pindah-kepemilikan-produk",
                         json={"item": nilai, "jumlah": 550})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
    finally:
        await c.aclose()

    from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah
    async with pg() as db:
        gabungan = await hitung_stok_broken_curah(
            db, jasa_id=[titipan["jasa1"], titipan["jasa2"]])
    assert gabungan == pytest.approx(50.0)


# ═══════════════ Halaman: pemindahan curah di kartu produknya ═══════════════

async def test_halaman_jasa_menampilkan_tombol_curah_di_kartu_broken(
    pg, titipan,
):
    """Keluhan pemilik: "bekatulnya kenapa tidak ada di halaman produk jasa?
    tetap harus ada." Bekatul tampil sebagai INFORMASI (tanpa tombol — sudah
    milik pabrik sejak dibukukan); broken curah tampil dengan tombol yang
    nilainya menyebut SELURUH jasa_ids pelanggan ini."""
    import re

    from app.database import now_local
    from app.models import ByproductStock, User
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.stok import barang_jadi_g2

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        kini = now_local()
        db.add(ByproductStock(jenis_produk="bekatul", source_type="polishing",
                              source_id=1, berat_kg=800, tanggal=kini.date(),
                              waktu=kini, input_by=u.id, jasa_id=None))
        # Hasil samping berkarung tiap jenis harus punya kontrol transfer
        # pada kartu yang sama; cabang kemasan otomatis sebelumnya melewati
        # daftar SKU dan menghilangkan tombolnya.
        for jenis in ("broken", "menir", "reject"):
            db.add(PolishingOutputLog(
                polishing_process_id=1, jenis=jenis, berat_kg=100,
                waktu_update=kini, input_by=u.id))
        await db.commit()
        for jenis in ("broken", "menir", "reject"):
            await catat_packing(
                db, user=u, kode_pol="POL-UJIT-01", kategori=jenis,
                material_kode="bekas", ukuran=50, jumlah_karung=1)
        stok_jadi = await barang_jadi_g2(db)
        expected_bj = {
            k["jenis"]: f"bj:{k['sku_id']}|{k['std_id'] or ''}|{titipan['jasa1']}"
            for k in stok_jadi.samping if k.get("jasa_id") == titipan["jasa1"]
            and k["jenis"] in ("broken", "menir", "reject")
        }

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/stok-produk-jasa")
    finally:
        await c.aclose()
    assert r.status_code == 200
    assert "Bekatul dari hasil sosoh" in r.text
    assert "sudah dipindahkan ke milik pabrik" in r.text
    assert "Broken (curah), sudah dicatat" not in r.text
    # Himpunan id, bukan string persis — urutannya tak dijamin (lihat
    # catatan `jasa_ids_per_pelanggan_dengan_hasil`), maknanya yang harus
    # sama: SELURUH jasa_ids pelanggan ini, bukan cuma salah satu.
    cocok = re.search(r"cr:broken\|([\d,]+)", r.text)
    assert cocok, "tombol pindah broken curah tak ditemukan di halaman"
    assert {int(x) for x in cocok.group(1).split(",")} == {
        titipan["jasa1"], titipan["jasa2"]}
    # Kontrol pemindahan harus berada di dalam detail kartu Broken yang
    # memuat saldo curahnya, bukan tampil sebagai kartu lepas di bawah daftar.
    kartu_broken = re.search(
        r'<details class="padat padat--samping">(?:(?!</details>).)*'
        r'Broken(?:(?!</details>).)*cr:broken\|[\d,]+(?:(?!</details>).)*</details>',
        r.text, re.S,
    )
    assert kartu_broken, "tombol broken curah harus berada di kartu Broken"
    # Kontrol barang berkarung Reject, Menir, dan Broken juga harus ada.
    for jenis in ("broken", "menir", "reject"):
        assert jenis in expected_bj
        nilai_bj = re.escape(expected_bj[jenis])
        kartu = re.search(
            r'<details class="padat padat--samping">(?:(?!</details>).)*'
            + jenis + r"(?:(?!</details>).)*nilai=" + nilai_bj
            + r"(?:(?!</details>).)*</details>", r.text, re.S | re.I,
        )
        assert kartu, f"tombol transfer barang berkarung {jenis} tak ada di kartunya"


async def test_bekatul_dikarungi_dari_proses_jasa_tetap_tersebut(pg, titipan):
    """Laporan lapangan 6 Oktober 2026: *"saya baru saja packing bekatul dari
    proses jasa. tetapi tidak ada di halaman produk jasa."* — lalu koreksi
    yang lebih dalam: *"jadi stock terpisah sampai pindah kepemilikan"*,
    membalik keputusan pemilik 12. `titipan` memakai `HASIL_DITAHAN_BAWAAN`
    baru ("sekam" saja), jadi bekatul proses jasa1 di sini TETAP milik
    pesanan — bukan baris informasi pabrik lagi, melainkan kartu PENUH
    (sebangun broken/menir/reject) di blok "Hasil samping", dengan karungnya
    bertombol "Pindah kepemilikan" persis seperti kemasan lain.
    """
    from app.database import now_local
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.models import User

    async with pg() as db:
        db.add(PolishingOutputLog(
            polishing_process_id=1,  # POL-UJIT-01, proses jasa1
            jenis="bekatul", berat_kg=900, waktu_update=now_local(),
            input_by=titipan["user"]))
        await db.commit()
        u = await db.get(User, titipan["user"])
        await catat_packing(db, user=u, kode_pol="POL-UJIT-01",
                            kategori="bekatul", material_kode="bekas",
                            ukuran=40, jumlah_karung=20)      # 800 kg

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/stok-produk-jasa")
    finally:
        await c.aclose()
    assert r.status_code == 200
    # Kartu PENUH di "Hasil samping" — bukan baris informasi pabrik: judulnya
    # "Bekatul" saja (pola `padat--samping`, sebangun broken/menir/reject),
    # dan "Tercatat" (800, dikarungi) + "Belum dicatat" (100, belum singgah
    # jalur mana pun) menjumlah persis hasil mesin (900).
    assert "Bekatul dari hasil sosoh" not in r.text, \
        "bekatul masih dibaca sebagai milik pabrik — hasil_ditahan tak terbaca"
    assert ">Bekatul<" in r.text and ">900<" in r.text
    assert "800&nbsp;kg · 20&nbsp;krg" in r.text, \
        "bekatul yang dikarungi tak tersebut angkanya (800 kg, 20 karung)"
    # Tombol pindah kepemilikan untuk karungnya — sama seperti kemasan lain,
    # tak perlu pengkabelan baru (lihat docstring `pemilik_hasil`).
    assert "buka=pindah_kepemilikan_produk&amp;nilai=bj:" in r.text, \
        "tombol pindah kepemilikan bekatul (karung) tak muncul"


# ═══ Kartu Stok Produk — curah BENAR-BENAR berpindah, bukan cuma bergeser ═══
#
# Laporan lapangan 7 Oktober 2026, langsung sesudah tombol "Pindah
# kepemilikan" bekatul curah dipakai sungguhan: *"angka dari stock jasa
# tidak berkurang dan di stok produk juga tidak bertambah, malah statusnya
# informasi tentang berapa yang sudah di packing hilang."* Lalu: *"coba
# check lagi juga untuk reject, menir dan broken."*
#
# `hitung_stok_bekatul`/`hitung_stok_broken_curah` SUDAH benar (dibuktikan
# di atas) — yang salah adalah `curah`/`dikemas` DI KARTU `stok_produk()`,
# yang membaca "sudah dicatat" lewat kepemilikan SAAT INI. Baris yang
# berpindah `jasa_id` lenyap dari situ, dan kartunya membacanya seolah
# belum pernah dicatat — bukan berkurang di satu sisi, bertambah di sisi
# lain. Reject & menir tak ikut diuji di sini: keduanya tak punya jalan
# curah (`byproduct_stock`) sama sekali — cuma `catat_packing`, yang sudah
# diuji di `test_pindah_barang_jadi_*` di atas dan tak tersentuh cacat ini
# (lihat `dikemas_proc`: scoping-nya sama, tapi `titipan` di atas tak
# pernah menguji KARTUNYA sesudah pindah — jadi dites juga di bawah).

@pytest.fixture
async def proses_jasa_curah(pg, pemakai):
    """Satu pesanan jasa, satu proses sosoh: 900 kg bekatul DAN 900 kg broken
    keluar mesin, 500 kg masing-masing sudah dicatat curah — cukup untuk
    membuktikan kartu `stok_produk()` bergerak BENAR sesudah sebagiannya
    pindah kepemilikan (400 kg selalu tersisa "belum dicatat", tak tersentuh
    pemindahan apa pun)."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Jasa, Pelanggan, Silo, User, Warehouse
    from app.penggilingan.gudang2.models import (PolishingOutputLog, PolishingProcess,
                                                  PolishingSiloUsage)
    from app.penggilingan.inventory.finished_goods import catat_bekatul, catat_broken
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        silo = (await db.execute(select(Silo).where(
            Silo.warehouse_id == g2.id))).scalars().first()
        if silo is None:
            silo = Silo(nama_silo="Silo A", warehouse_id=g2.id)
            db.add(silo)
            await db.flush()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        pel = Pelanggan(nama_pelanggan="Pak Budi")
        db.add(pel)
        await db.flush()
        jasa = Jasa(kode="JAS-2610-010", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.flush()
        p = PolishingProcess(kode_proses="POL-UJIC-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=u.id, jasa_id=jasa.id)
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo.id,
                                  berat_awal_kg=9_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=9_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="bekatul",
                                  berat_kg=900, waktu_update=now_local(), input_by=u.id))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="broken",
                                  berat_kg=900, waktu_update=now_local(), input_by=u.id))
        await db.commit()
        await catat_bekatul(db, user=u, kode_pol=p.kode_proses, berat_kg=500)
        await catat_broken(db, user=u, kode_pol=p.kode_proses, berat_kg=500)
    return {"user": pemakai.id, "jasa_id": jasa.id, "kode": p.kode_proses}


async def _kartu_jasa_pabrik(pg, jasa_id, jenis):
    from app.services.stok import stok_produk

    async with pg() as db:
        kartu_jasa = {k.jenis: k for k in await stok_produk(db, jasa_id=jasa_id)}
        kartu_pabrik = {k.jenis: k for k in await stok_produk(db)}
    return kartu_jasa.get(jenis), kartu_pabrik.get(jenis)


@pytest.mark.parametrize("jenis,fungsi_pindah", [
    ("bekatul", "pindah_kepemilikan_bekatul_curah"),
    ("broken", "pindah_kepemilikan_broken_curah"),
])
async def test_pindah_curah_benar_benar_berpindah_di_kartu_stok_produk(
    pg, proses_jasa_curah, jenis, fungsi_pindah,
):
    """Sebelum pindah: jasa sisa 900 (400 belum dicatat + 500 tercatat
    curah), pabrik belum punya kartu sama sekali. Sesudah memindah 300 kg:
    jasa WAJIB turun jadi 600 (400 belum dicatat TETAP — pindah kepemilikan
    tak "membongkar" yang sudah dicatat — 200 tercatat curah), pabrik WAJIB
    naik jadi 300 (seluruhnya tercatat; bekatul/broken pabrik tak datang
    dari satu proses pun miliknya sendiri, jadi "belum dicatat"-nya nol)."""
    from app.models import User
    from app.penggilingan.inventory import finished_goods as fg

    jasa, pabrik = await _kartu_jasa_pabrik(pg, proses_jasa_curah["jasa_id"], jenis)
    assert (jasa.hasil_kg, jasa.curah_kg, jasa.dikemas_kg, jasa.sisa_kg) == (
        900, pytest.approx(400), pytest.approx(500), pytest.approx(900))
    assert pabrik is None, f"belum ada kartu {jenis} pabrik sebelum pindah: {pabrik}"

    async with pg() as db:
        u = await db.get(User, proses_jasa_curah["user"])
        await getattr(fg, fungsi_pindah)(
            db, user=u, jasa_id=proses_jasa_curah["jasa_id"], berat_kg=300)

    jasa, pabrik = await _kartu_jasa_pabrik(pg, proses_jasa_curah["jasa_id"], jenis)
    assert jasa.hasil_kg == 900, "hasil mesin tak boleh berubah oleh pindah kepemilikan"
    assert jasa.curah_kg == pytest.approx(400), (
        f"'belum dicatat' jasa wajib TETAP 400, bukan {jasa.curah_kg} — pindah "
        "kepemilikan tak boleh membuat yang sudah dicatat terbaca belum dicatat")
    assert jasa.dikemas_kg == pytest.approx(200), \
        f"'tercatat' jasa wajib turun jadi 200, bukan {jasa.dikemas_kg}"
    assert jasa.sisa_kg == pytest.approx(600), \
        f"sisa jasa wajib BERKURANG 300 kg (900→600), bukan {jasa.sisa_kg}"

    assert pabrik is not None, f"kartu {jenis} pabrik wajib muncul sesudah menerima pindahan"
    assert pabrik.hasil_kg == 0, "pabrik tak pernah menyosoh ini sendiri"
    assert pabrik.curah_kg == pytest.approx(0), \
        f"pabrik tak punya 'belum dicatat' sendiri untuk {jenis} ini, {pabrik.curah_kg}"
    assert pabrik.dikemas_kg == pytest.approx(300), \
        f"'tercatat' pabrik wajib naik jadi 300, bukan {pabrik.dikemas_kg}"
    assert pabrik.sisa_kg == pytest.approx(300), \
        f"sisa pabrik wajib BERTAMBAH 300 kg (0→300), bukan {pabrik.sisa_kg}"


async def test_pindah_barang_jadi_benar_benar_berpindah_di_kartu_stok_produk(pg, titipan):
    """Sebangun `test_pindah_curah_benar_benar_berpindah_di_kartu_stok_produk`,
    tapi untuk jalur BERKARUNG (`pindah_kepemilikan_barang_jadi`, dipakai
    beras/menir/reject — TAK PUNYA jalur curah sendiri). Laporan lapangan 9
    Oktober 2026: "beras pindah kepemilikan hilang dari stok jasa maupun
    stok sendiri". Dibuktikan di sini TIDAK — `hasil_kg` pabrik memang 0
    (pabrik tak pernah menyosoh medium Bu Sri sendiri, sama seperti bekatul/
    broken), tapi `dikemas_kg`/`sisa_kg` persis mengikuti jumlah yang
    dipindah, di KEDUA sisi.

    `titipan`: jasa1 (p1 = POL-UJIT-01) menghasilkan 5.000 kg medium, 20
    karung (500 kg, 25 kg/karung) sudah dipacking — belum ada kartu medium
    pabrik sama sekali.
    """
    from app.models import User
    from app.penggilingan.inventory.finished_goods import pindah_kepemilikan_barang_jadi

    jasa, pabrik = await _kartu_jasa_pabrik(pg, titipan["jasa1"], "medium")
    assert (jasa.hasil_kg, jasa.dikemas_kg, jasa.curah_kg, jasa.sisa_kg) == (
        5_000, pytest.approx(500), pytest.approx(4_500), pytest.approx(5_000))
    assert pabrik is None, f"belum ada kartu medium pabrik sebelum pindah: {pabrik}"

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        berat = await pindah_kepemilikan_barang_jadi(
            db, user=u, sku_id=titipan["sku_id"], standard_id=titipan["std_id"],
            jasa_id=titipan["jasa1"], karung=5)
    assert berat == pytest.approx(125)  # 5 karung x 25 kg

    jasa, pabrik = await _kartu_jasa_pabrik(pg, titipan["jasa1"], "medium")
    assert jasa.hasil_kg == 5_000, "hasil mesin tak boleh berubah oleh pindah kepemilikan"
    assert jasa.curah_kg == pytest.approx(4_500), (
        f"'belum dicatat' jasa wajib TETAP 4.500, bukan {jasa.curah_kg} — pindah "
        "kepemilikan karung tak boleh menggeser yang belum pernah dikemas sama sekali")
    assert jasa.dikemas_kg == pytest.approx(375), \
        f"dikemas jasa wajib turun jadi 375 (500-125), bukan {jasa.dikemas_kg}"
    assert jasa.sisa_kg == pytest.approx(4_875), \
        f"sisa jasa wajib BERKURANG 125 kg (5.000→4.875), bukan {jasa.sisa_kg}"

    assert pabrik is not None, (
        "kartu medium pabrik WAJIB muncul sesudah menerima pindahan — bila ini "
        "None, beras yang dipindah genuinely hilang, bukan sekadar 'hasil 0'")
    assert pabrik.hasil_kg == 0, (
        "pabrik tak pernah menyosoh medium Bu Sri sendiri — nol di sini BENAR, "
        "sama seperti kartu bekatul/broken pabrik yang menerima pindahan curah; "
        "'Hasil sosoh' kosong bukan tanda kehilangan, lihat `dikemas_kg`/`sisa_kg`")
    assert pabrik.curah_kg == pytest.approx(0), \
        f"pabrik tak punya 'belum dikemas' sendiri untuk medium ini, {pabrik.curah_kg}"
    assert pabrik.dikemas_kg == pytest.approx(125), \
        f"dikemas pabrik wajib jadi 125 (persis yang dipindah), bukan {pabrik.dikemas_kg}"
    assert pabrik.sisa_kg == pytest.approx(125), \
        f"sisa pabrik wajib BERTAMBAH persis 125 kg (0→125), bukan {pabrik.sisa_kg}"
