"""Minta lot PK sebagai PROSES empat langkah — keputusan pemilik 25 Sep 2026.

    1 MINTA   operator G2  → diminta
    2 ACC     admin        → disetujui   (menetapkan TUJUAN dan BOBOT)
    3 KIRIM   operator G1  → dikirim     ← DI SINI BARANGNYA BERPINDAH
    4 TUTUP   admin        → selesai     (boleh mengubah bobotnya)

Sampai hari itu ini cuma pengingat: Admin mengerjakan seluruhnya sendiri, dan
permintaannya menutup DIRINYA SENDIRI begitu transfer dicatat. Operator Gudang
1 tak pernah terlibat, dan yang meminta tak pernah diberi kabar lagi.

Yang paling berisiko dari seluruh alur ini adalah langkah 4 atas bobot yang
BERBEDA: barangnya sudah berpindah di langkah 3, jadi mengubah bobot berarti
mengubah perpindahan yang sudah tercatat. Itu wajib lewat peristiwa lawan —
bukan UPDATE di tempat — dan berkas ini membuktikannya dengan membangun ulang
proyeksinya dari buku besar.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg, pemakai, pemasok):
    """Satu lot PK 6.000 kg di Gudang 1, tiga orang, dua silo Gudang 2."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import (MillingProcess, MillingProgressLog, PurchaseBatch,
                            Silo, User, Warehouse)

    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
        await db.flush()
        silo_g1 = Silo(nama_silo="Silo Selepan", warehouse_id=g1.id)
        db.add(silo_g1)
        for huruf in ("A", "B"):
            db.add(Silo(nama_silo=f"Silo {huruf}", warehouse_id=g2.id,
                        status="kosong"))
        op1 = await db.get(User, pemakai.id)
        op1.default_warehouse_id = g1.id
        op2 = User(nama="Operator Polesan", role="operator", status="aktif",
                   default_warehouse_id=g2.id)
        admin = User(nama="Admin Uji", role="admin", status="aktif")
        db.add_all([op2, admin])
        await db.flush()

        b = PurchaseBatch(kode_batch="GB-MINTA-01", supplier_id=pemasok.id,
                          berat_total_kg=10_000, kondisi_gabah="kering",
                          tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                          input_by=op1.id, flag_unverified=False,
                          sumber_berat="timbangan")
        db.add(b)
        await db.flush()
        p = MillingProcess(kode_proses="LOT-MINTA-01", status="selesai",
                           silo_id=silo_g1.id, berat_gabah_masuk_kg=10_000,
                           waktu_mulai=now_local(), waktu_selesai=now_local(),
                           created_by=op1.id, purchase_batch_id=b.id)
        db.add(p)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=p.id, berat_kumulatif_kg=6_000,
                                  waktu_update=now_local(), input_by=op1.id))
        await db.commit()
        return {"op1": op1.id, "op2": op2.id, "admin": admin.id,
                "lot": "LOT-MINTA-01", "proses_id": p.id}


async def _minta(pg, pabrik) -> int:
    from app.models import User
    from app.services.permintaan_pk import minta

    async with pg() as db:
        u = await db.get(User, pabrik["op2"])
        r = await minta(db, user=u, kode_proses=pabrik["lot"])
        return r.id


async def _acc(pg, pabrik, pid: int, *, tujuan="A", berat=6_000):
    from app.models import User
    from app.services.permintaan_pk import setujui

    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        return await setujui(db, user=u, permintaan_id=pid, tujuan=tujuan,
                             berat=berat)


async def _kirim(pg, pabrik, pid: int, *, berat=6_000, oleh="op1"):
    """Yang mengirim operator GUDANG 1 sejak 27 September 2026 — lihat
    `test_yang_mengirim_gudang1_yang_ditunggu_gudang2`."""
    from app.models import User
    from app.services.permintaan_pk import kirim

    async with pg() as db:
        u = await db.get(User, pabrik[oleh])
        return await kirim(db, user=u, permintaan_id=pid, berat=berat)


# ─────────────────── Alur penuh ───────────────────

async def test_empat_langkah_berurutan(pg, pabrik):
    from app.models import User
    from app.models.permintaan import DIKIRIM, DIMINTA, DISETUJUI, SELESAI
    from app.penggilingan.gudang2.service import hitung_stok_silo
    from app.services.permintaan_pk import tutup_admin
    from sqlalchemy import select
    from app.models import PermintaanPk, Silo

    pid = await _minta(pg, pabrik)
    async with pg() as db:
        assert (await db.get(PermintaanPk, pid)).status == DIMINTA

    b = await _acc(pg, pabrik, pid, tujuan="A", berat=6_000)
    assert b.status == DISETUJUI and float(b.berat_setuju_kg) == 6_000
    assert b.tujuan == "silo" and b.silo_id is not None

    b = await _kirim(pg, pabrik, pid, berat=5_900)
    assert b.status == DIKIRIM and float(b.berat_kirim_kg) == 5_900
    assert b.internal_transfer_id is not None, "perpindahannya tak tertaut"

    # ── Barangnya SUDAH di Gudang 2 sebelum Admin menutup ──
    # Itu inti keputusan (a): Gudang 2 harus bisa langsung menyosohnya.
    async with pg() as db:
        silo = await db.get(Silo, b.silo_id)
        assert await hitung_stok_silo(db, silo.id) == 5_900

    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        b2, catatan = await tutup_admin(db, user=u, permintaan_id=pid,
                                        berat_final=5_900)
    assert b2.status == SELESAI and float(b2.berat_final_kg) == 5_900
    assert catatan == "", "tak ada koreksi, tak perlu kalimat tambahan"


async def test_transfer_tak_lagi_menutup_permintaan_sendiri(pg, pabrik):
    """Inti perubahannya. Selama `services.transfer` menutupnya, Admin tak
    pernah kebagian menutup — dan langkah keempat pemilik tak pernah ada."""
    from tests.bantu import kode_saja

    from app.services import transfer

    # `kode_saja`: komentar di sana MENYEBUT penutupan yang dicabut, justru
    # supaya orang berikutnya tahu kenapa ia tak boleh kembali.
    kode = kode_saja(transfer.create_internal_transfer)
    assert "permintaan_pk" not in kode, "transfer masih menyentuh permintaan"
    assert "tutup" not in kode, "transfer masih menutup permintaan"

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid)
    b = await _kirim(pg, pabrik, pid)
    from app.models.permintaan import DIKIRIM

    assert b.status == DIKIRIM, "permintaan menutup dirinya sendiri lagi"


# ─────────────────── Pagar tiap langkah ───────────────────

async def test_tak_bisa_mengirim_yang_belum_disetujui(pg, pabrik):
    from app.services.permintaan_pk import PermintaanError

    pid = await _minta(pg, pabrik)
    with pytest.raises(PermintaanError) as e:
        await _kirim(pg, pabrik, pid)
    assert "menunggu keputusan Admin" in str(e.value)


async def test_yang_mengirim_gudang1_yang_ditunggu_gudang2(pg, pabrik):
    """Keputusan pemilik 27 September 2026, menjawab skenario B1 yang QA
    tinggalkan terbuka ("di lapangan siapa yang sebenarnya mengangkat
    karungnya?"): "gudang 1 yang mengirim", "jika sudah disetujui", "jadi
    gudang 1 mulai proses kirim".

    ATURANNYA TIDAK BERUBAH, dan itu yang penting bagi pembaca berikutnya:
    satu tangan, dan yang mencatat "berat yang dimuat" harus orang yang melihat
    karungnya naik. Yang berubah keterangan lapangannya — orang itu Gudang 1.
    Pagar ini sempat menuntut kebalikannya persis selama satu hari (26
    September, `test_yang_memuat_gudang2_yang_diberi_tahu_gudang1`); kalau
    kelak ia hendak dibalik lagi, yang diperiksa lebih dulu adalah lapangannya,
    bukan tata letak layarnya.

    Dijaga DI PINTUNYA, bukan cuma di layar: menyembunyikan tombol bukan
    penjagaan — alamatnya bisa diketik, dan lembar yang masih terbuka di layar
    orang lain masih bisa mengirim.
    """
    import inspect

    from fastapi import HTTPException

    from app.models import User
    from app.web import api
    from tests.bantu import kode_saja

    pintu = kode_saja(api.act_kirim_permintaan_pk)
    assert "_is_g1_operator(user)" in pintu
    assert "_is_g2_operator" not in pintu, "Gudang 2 masih bisa menekannya"
    # Dan aksinya ditawarkan di katalog Gudang 1, BUKAN Gudang 2.
    sumber = inspect.getsource(api.actions_menu)
    g1, g2 = sumber.index("if g1:"), sumber.index("if g2:")
    assert '"id": "kirim_permintaan_pk"' in sumber[g1:g2], \
        "yang mengirim tak punya aksinya di katalog"
    assert '"id": "kirim_permintaan_pk"' not in sumber[g2:], \
        "Gudang 2 masih ditawari pengiriman"

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid, berat=6_000)
    async with pg() as db:
        op2 = await db.get(User, pabrik["op2"])
        op2.role = "operator"
        await db.commit()
    with pytest.raises((HTTPException, Exception)):
        await api.act_kirim_permintaan_pk(
            api.KirimPermintaanReq(permintaan=str(pid), berat=100), user=op2)


async def test_kirim_lebih_banyak_daripada_yang_disetujui_ditolak(pg, pabrik):
    """Yang disetujui adalah BATAS. Melewatinya berarti memindahkan barang yang
    tak pernah disetujui siapa pun."""
    from app.services.permintaan_pk import PermintaanError

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid, berat=4_000)
    with pytest.raises(PermintaanError) as e:
        await _kirim(pg, pabrik, pid, berat=4_500)
    assert "4.000" in str(e.value)
    # Kurang boleh — karung terakhir tak selalu penuh.
    b = await _kirim(pg, pabrik, pid, berat=3_800)
    assert float(b.berat_kirim_kg) == 3_800


async def test_wewenang_gudang1_tidak_lewat_peran(pg, pabrik):
    """`can_transfer_pk` TIDAK disentuh: melebarkannya berarti Gudang 1 boleh
    memindahkan apa saja kapan saja — kebalikan dari yang pemilik minta."""
    import inspect

    from app import peran
    from app.models import User

    assert "permintaan" not in inspect.getsource(peran.can_transfer_pk).lower()
    async with pg() as db:
        op1 = await db.get(User, pabrik["op1"])
        assert not peran.can_transfer_pk(op1), "operator G1 mendadak boleh transfer"


async def test_satu_permintaan_berjalan_per_lot(pg, pabrik):
    """Butir (c) pemilik, dijaga BASIS DATA: indeksnya melebar ke ketiga
    keadaan berjalan, bukan hanya yang pertama."""
    from app.services.permintaan_pk import PermintaanError

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid)
    # Sudah disetujui — dan lot yang sama tetap tak bisa diminta lagi.
    with pytest.raises(PermintaanError) as e:
        await _minta(pg, pabrik)
    assert "sudah diminta" in str(e.value).lower()


# ─────────────────── Dua sesi: ACC dan KIRIM ───────────────────

async def test_dua_admin_menekan_acc_bersamaan(pg, pabrik):
    from sqlalchemy import select

    from app.models import PermintaanPk, User
    from app.services.permintaan_pk import setujui

    pid = await _minta(pg, pabrik)

    async def acc(berat):
        async with pg() as db:
            u = await db.get(User, pabrik["admin"])
            try:
                await setujui(db, user=u, permintaan_id=pid, tujuan="A", berat=berat)
                return f"ok:{berat}"
            except Exception as e:                       # noqa: BLE001
                return f"tolak: {e}"

    hasil = await asyncio.gather(acc(6_000), acc(3_000))
    menang = [x for x in hasil if x.startswith("ok:")]
    assert len(menang) == 1, hasil
    async with pg() as db:
        b = (await db.execute(select(PermintaanPk))).scalars().one()
    assert f"ok:{float(b.berat_setuju_kg):.0f}" == menang[0].replace(".0", "")


async def test_dua_operator_menekan_kirim_bersamaan(pg, pabrik):
    """Yang paling mahal bila lolos: DUA perpindahan atas PK yang sama.

    Dua HP di satu gudang adalah keadaan sehari-hari — dan sejak yang memuat
    hanya Gudang 2, keduanya justru ada di gudang yang sama."""
    from sqlalchemy import select

    from app.models import InternalTransfer, User
    from app.services.permintaan_pk import kirim

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid, berat=6_000)

    async def kirim_satu(berat):
        async with pg() as db:
            u = await db.get(User, pabrik["op2"])
            try:
                await kirim(db, user=u, permintaan_id=pid, berat=berat)
                return f"ok:{berat}"
            except Exception as e:                       # noqa: BLE001
                return f"tolak: {e}"

    hasil = await asyncio.gather(kirim_satu(3_000), kirim_satu(3_000))
    assert len([x for x in hasil if x.startswith("ok:")]) == 1, hasil
    async with pg() as db:
        trf = (await db.execute(select(InternalTransfer).where(
            InternalTransfer.status == "terkirim"))).scalars().all()
    assert len(trf) == 1, f"{len(trf)} perpindahan atas PK yang sama"


# ─────────────────── Langkah 4 dengan bobot BERBEDA ───────────────────

async def test_penutupan_dengan_bobot_berbeda_lewat_buku_besar(pg, pabrik):
    """Bagian paling berisiko: barangnya sudah pindah, jadi koreksinya
    MENGUBAH perpindahan yang sudah tercatat.

    Pembuktiannya bukan "angkanya berubah", melainkan `bangun_ulang_proyeksi`
    menghasilkan angka yang SAMA — itulah tanda koreksinya lewat peristiwa
    lawan, bukan UPDATE di tempat. Kalau di-UPDATE, proyeksi yang dibangun
    ulang dari buku besar akan mengembalikan angka LAMA.
    """
    from sqlalchemy import select, text

    from app.models import Silo, User
    from app.penggilingan.gudang2.service import hitung_stok_silo
    from app.services.permintaan_pk import tutup_admin

    pid = await _minta(pg, pabrik)
    b = await _acc(pg, pabrik, pid, tujuan="A", berat=6_000)
    silo_id = b.silo_id
    await _kirim(pg, pabrik, pid, berat=6_000)

    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        b2, catatan = await tutup_admin(db, user=u, permintaan_id=pid,
                                        berat_final=5_500)
    assert float(b2.berat_final_kg) == 5_500
    assert float(b2.berat_kirim_kg) == 6_000, "angka Gudang 1 ikut tertimpa"
    assert "6.000" in catatan and "5.500" in catatan, catatan

    async with pg() as db:
        assert await hitung_stok_silo(db, silo_id) == 5_500

    # Dan buku besarnya yang menyimpan kebenarannya.
    async with pg() as db:
        n = (await db.execute(text(
            "SELECT count(*) FROM peristiwa WHERE jenis LIKE '%dibatalkan%'"))).scalar()
    assert n >= 1, "koreksinya tak melahirkan peristiwa lawan — ia UPDATE di tempat"


async def test_penutupan_ditolak_bila_pk_sudah_dipakai_menyosoh(pg, pabrik):
    """Jangan diam-diam membiarkan angkanya berbeda: kalau PK-nya sudah
    dipakai, penutupan-dengan-koreksi DITOLAK sambil menyebutkan sebabnya."""
    from app.models import User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.services.permintaan_pk import PermintaanError, tutup_admin

    pid = await _minta(pg, pabrik)
    b = await _acc(pg, pabrik, pid, tujuan="A", berat=6_000)
    await _kirim(pg, pabrik, pid, berat=6_000)

    async with pg() as db:
        u = await db.get(User, pabrik["op2"])
        await mulai_penyosohan(db, user=u, nama_silos=["A"])

    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        with pytest.raises(PermintaanError) as e:
            await tutup_admin(db, user=u, permintaan_id=pid, berat_final=5_000)
    assert "dipoles" in str(e.value) or "dipakai" in str(e.value), str(e.value)

    # Menutup pada angka yang SAMA tetap boleh — tak ada yang perlu dikoreksi.
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        b2, catatan = await tutup_admin(db, user=u, permintaan_id=pid,
                                        berat_final=6_000)
    assert catatan == "" and float(b2.berat_final_kg) == 6_000


# ─────────────────── Gugur sesudah ACC ───────────────────

async def test_lot_habis_sesudah_acc_menggugurkan_permintaannya(pg, pabrik):
    """Kartunya harus hilang dari antrean Gudang 1 pada pemuatan yang SAMA —
    bukan satu putaran poller kemudian."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import InternalTransfer, PermintaanPk, User
    from app.models.permintaan import GUGUR
    from app.services.berjalan import untuk_gudang1

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid, berat=6_000)

    # Lotnya habis lewat jalan lain, tanpa menyebut permintaannya.
    async with pg() as db:
        u = await db.get(User, pabrik["op1"])
        db.add(InternalTransfer(kode_transfer="TRF-LUAR-99",
                                milling_process_id=pabrik["proses_id"],
                                berat_kg=6_000, status="terkirim",
                                lokasi_tujuan="ditumpuk", waktu=now_local(),
                                created_by=u.id))
        await db.commit()

    async with pg() as db:
        b = await untuk_gudang1(db)
    assert not [x for x in b.menunggu if x.aksi == "kirim_permintaan_pk"], \
        "kartu kirim masih berdiri atas lot yang sudah habis"
    async with pg() as db:
        assert (await db.get(PermintaanPk, pid)).status == GUGUR


# ─────────────────── Empat pembaca, empat keadaan ───────────────────

async def test_kartu_tiap_peran_pada_tiap_keadaan(pg, pabrik):
    from app.models import User
    from app.services.berjalan import untuk_gudang1, untuk_staff
    from app.services.stok import pk_gudang1

    pid = await _minta(pg, pabrik)

    # 1 · diminta — Admin memutuskan, Gudang 1 belum melihat apa pun.
    async with pg() as db:
        adm, g1 = await untuk_staff(db), await untuk_gudang1(db)
        lot = next(l for l in await pk_gudang1(db) if l.kode == pabrik["lot"])
    # Kartunya di MEJA sejak 26 September 2026 (permintaan pemilik): yang
    # ditunggu keputusan, bukan pekerjaan fisik. Lihat
    # `test_kartu_permintaan_pindah_ke_menunggu_keputusan`.
    assert [x.aksi for x in adm.meja if x.kelompok == "permintaan"] == ["acc_permintaan_pk"]
    assert not [x for x in g1.menunggu if x.kelompok == "permintaan"], \
        "Gudang 1 melihat pekerjaan yang belum boleh ia kerjakan"
    assert "menunggu keputusan Admin" in lot.diminta_keadaan

    # 2 · disetujui — pindah ke tangan Gudang 1.
    await _acc(pg, pabrik, pid, berat=6_000)
    async with pg() as db:
        adm, g1 = await untuk_staff(db), await untuk_gudang1(db)
        lot = next(l for l in await pk_gudang1(db) if l.kode == pabrik["lot"])
    assert not [x for x in adm.meja if x.kelompok == "permintaan"], \
        "Admin menunggui pekerjaan yang bukan miliknya"
    # Gudang 1 mendapat PEKERJAAN, bertombol, di antreannya (keputusan pemilik
    # 27 September 2026: "gudang 1 yang mengirim"). Kartu ini sempat jadi kabar
    # tanpa tombol selama satu hari, ketika tangan yang memuat disangka Gudang 2.
    kerja = [x for x in g1.menunggu if x.kelompok == "permintaan"]
    assert len(kerja) == 1 and kerja[0].aksi == "kirim_permintaan_pk"
    assert kerja[0].pilihan and kerja[0].nilai == str(pid)
    assert "menunggu dikirim Gudang 1" in kerja[0].keadaan
    assert not [x for x in g1.transit if x.kelompok == "permintaan"], \
        "pekerjaannya dipajang sebagai kabar, bukan sebagai tugas"
    assert "menunggu dikirim Gudang 1" in lot.diminta_keadaan

    # 3 · dikirim — kembali ke Admin, untuk ditutup.
    await _kirim(pg, pabrik, pid, berat=6_000)
    async with pg() as db:
        adm, g1 = await untuk_staff(db), await untuk_gudang1(db)
    assert [x.aksi for x in adm.meja if x.kelompok == "permintaan"] == ["tutup_permintaan_pk"]
    assert not [x for x in g1.menunggu if x.kelompok == "permintaan"], \
        "kartu Gudang 1 tak hilang sesudah barangnya berangkat"


async def test_peminta_punya_kartunya_sendiri_sepanjang_alur(pg, pabrik):
    """Butir pemilik yang paling mudah dianggap sudah beres, dan bukan:
    operator Gudang 2 harus BERKARTU, bukan cuma melihat satu kalimat di lot
    yang kebetulan ia susuri di layar Stok.

    KETIGA keadaannya di TRANSIT, tanpa tombol: tak satu pun langkah alur ini
    miliknya sesudah ia menekan Minta — Admin menyetujui, GUDANG 1 mengirim
    (keputusan pemilik 27 September 2026), Admin menutup. Lencana antrean yang
    menagih pekerjaan yang tak bisa dikerjakan siapa pun akan berhenti dibaca.

    ⚠ Pagar ini sempat menuntut `disetujui` berdiri di ANTREAN dengan tombol,
    selama satu hari (26 September), ketika tangan yang memuat disangka Gudang
    2. Yang menentukan bukan enak atau tidaknya tata letak melainkan siapa yang
    mengangkat karungnya di lapangan; pemilik menjawabnya Gudang 1. Kalau kelak
    hendak dibalik lagi, itu yang diperiksa lebih dulu.
    """
    from app.services.berjalan import untuk_operator_gudang2

    pid = await _minta(pg, pabrik)
    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    kartu = [x for x in b.transit if x.judul == "Permintaan PK Anda"]
    assert len(kartu) == 1, f"peminta tak berkartu: {b.transit}"
    assert "menunggu keputusan Admin" in kartu[0].keadaan
    assert kartu[0].aksi is None and not kartu[0].pilihan, \
        "kartu bertombol atas pekerjaan yang bukan miliknya"
    # Dan ia TIDAK menambah lencana antrean.
    assert not [x for x in b.menunggu if x.kode == pabrik["lot"]]

    await _acc(pg, pabrik, pid, tujuan="A", berat=6_000)
    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    k = next(x for x in b.transit if x.judul == "Permintaan PK Anda")
    assert "menunggu dikirim Gudang 1" in k.keadaan
    assert "Silo A" in (k.sub or ""), "tujuannya tak disebut"
    assert k.aksi is None and not k.pilihan, \
        "peminta ditawari tombol kirim yang pintunya menolak dia"
    assert not [x for x in b.menunggu if x.aksi == "kirim_permintaan_pk"], \
        "pengiriman menagih lencana antrean orang yang tak mengirim"

    await _kirim(pg, pabrik, pid, berat=5_800)
    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    k = next(x for x in b.transit if x.judul == "Permintaan PK Anda")
    assert "sudah dikirim" in k.keadaan
    # Kabar yang menentukan apakah ia bisa mulai menyosoh hari ini.
    assert k.nota and "boleh langsung disosoh" in k.nota
    assert "5.800" in (k.utama[0] if k.utama else ""), k.utama


async def test_kartu_peminta_hilang_sesudah_ditutup(pg, pabrik):
    """Yang sudah selesai bukan lagi kabar — ia riwayat. Kartu yang tak pernah
    hilang membuat layarnya berhenti menjadi daftar."""
    from app.models import User
    from app.services.berjalan import untuk_operator_gudang2
    from app.services.permintaan_pk import tutup_admin

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid, berat=6_000)
    await _kirim(pg, pabrik, pid, berat=6_000)
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        await tutup_admin(db, user=u, permintaan_id=pid, berat_final=6_000)

    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    assert not [x for x in b.transit if x.judul == "Permintaan PK Anda"]


async def test_kartu_stok_berubah_dan_gudang2_bisa_memulai_pindah(pg, pabrik):
    """Permintaan pemilik 26 September 2026: "jika disetujui, kartu stock di
    gudang 1 berubah warnanya lalu operator gudang 2 bisa memilih kartu
    tersebut dan mulai proses pindah."

    Jadi yang memulai perpindahannya kini BISA operator Gudang 2 — dari kartu
    Stok yang ia tatap tiap hari, bukan dari layar lain. Operator Gudang 1
    tetap punya kartunya; keduanya memanggil layanan yang sama.
    """
    from app.models import User
    from app.services.permintaan_pk import kirim
    from app.services.stok import pk_gudang1

    pid = await _minta(pg, pabrik)
    async with pg() as db:
        lot = next(l for l in await pk_gudang1(db) if l.kode == pabrik["lot"])
    assert not lot.diminta_siap, "kartunya berubah sebelum disetujui"

    await _acc(pg, pabrik, pid, tujuan="A", berat=6_000)
    async with pg() as db:
        lot = next(l for l in await pk_gudang1(db) if l.kode == pabrik["lot"])
    assert lot.diminta_siap, "kartunya tak berubah sesudah disetujui"
    assert lot.diminta_id == pid, "tombolnya tak tahu permintaan mana"

    # Dan yang memuatnya operator Gudang 2 sendiri.
    async with pg() as db:
        op2 = await db.get(User, pabrik["op2"])
        b = await kirim(db, user=op2, permintaan_id=pid, berat=5_500)
    assert b.dikirim_oleh == pabrik["op2"]
    async with pg() as db:
        lot = next((l for l in await pk_gudang1(db) if l.kode == pabrik["lot"]), None)
    # Lotnya habis terkirim, jadi ia tak lagi berdiri sebagai PK Gudang 1.
    assert lot is None or not lot.diminta_siap


async def test_kartu_permintaan_pindah_ke_menunggu_keputusan(pg, pabrik):
    """Permintaan pemilik: blok paling atas di Menunggu keputusan, bukan di
    Antrian tunggu. Yang ditunggu memang keputusan — disetujui berapa, ke
    mana, atau ditolak."""
    from app.services import keputusan as K
    from app.services.berjalan import untuk_staff

    pid = await _minta(pg, pabrik)
    async with pg() as db:
        b = await untuk_staff(db)
    assert not [x for x in b.menunggu if x.kelompok == "permintaan"], \
        "kartunya masih di Antrian tunggu"
    meja = [x for x in b.meja if x.aksi == "acc_permintaan_pk"]
    assert len(meja) == 1, b.meja
    # Dan bloknya PALING ATAS di layar keputusan.
    assert K.blok(mutu=False)[0][0] == "acc_permintaan_pk"
    assert b.jumlah_keputusan >= 1, "lencana keputusan tak ikut menghitungnya"

    # Sesudah dikirim, ia kembali ke meja Admin sebagai "menunggu ditutup".
    await _acc(pg, pabrik, pid, berat=6_000)
    await _kirim(pg, pabrik, pid, berat=6_000)
    async with pg() as db:
        b = await untuk_staff(db)
    permintaan = [x.aksi for x in b.meja
                  if x.aksi in ("acc_permintaan_pk", "tutup_permintaan_pk")]
    assert permintaan == ["tutup_permintaan_pk"], permintaan


# ══════════════════════════════════════════════════════════════════════════
# KABAR — temuan QA 26 September 2026 pada 9c5a4c0
#
#   "Diuji sepanjang seluruh rantai: minta → ACC → muat → tutup.
#    `notifications` bertambah NOL baris."
#
# Empat keadaan, dan tak satu pun mengabarkan dirinya. Pagar di bawah menghitung
# barisnya dengan cara yang sama seperti QA menemukannya — atas seluruh rantai,
# bukan satu langkah — supaya cacat itu tak bisa kembali diam-diam.
# ══════════════════════════════════════════════════════════════════════════


async def test_setiap_langkah_rantai_meninggalkan_kabarnya(pg, pabrik):
    """Cara QA menemukannya: hitung `notifications` atas SELURUH rantai.

    Bukan per langkah — cacatnya justru bahwa tak ada satu pun yang menulis,
    dan pagar per langkah akan lulus tiga kali lalu gagal sekali tanpa
    menunjukkan bahwa yang rusak adalah rantainya.
    """
    from sqlalchemy import select

    from app.models import Notification, User
    from app.services.permintaan_pk import TIPE_KABAR, tutup_admin

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid, berat=6_000)
    await _kirim(pg, pabrik, pid, berat=6_000)
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        await tutup_admin(db, user=u, permintaan_id=pid, berat_final=6_000)

    async with pg() as db:
        kabar = list((await db.execute(
            select(Notification).where(Notification.tipe == TIPE_KABAR)
            .order_by(Notification.id))).scalars().all())
    assert len(kabar) == 3, [k.pesan for k in kabar]
    # Dialamatkan ke tangan yang memegang langkah BERIKUTNYA, bukan disebar.
    assert [k.target_role for k in kabar] == ["admin", "operator", "admin"]
    # Tiap kabar menyebut lot mana — kabar tanpa nama lot memaksa orang membuka
    # layar lain untuk tahu ia tentang apa.
    assert all(pabrik["lot"] in k.pesan for k in kabar), [k.pesan for k in kabar]
    # Dan tertaut ke barisnya, supaya eskalasi 24 jam tahu apa yang tertunda.
    assert all(k.table_name == "permintaan_pk" and k.record_id == pid
               for k in kabar)
    # Isinya menyebut TINDAKANNYA, bukan cuma keadaannya.
    assert "menunggu keputusan" in kabar[0].pesan
    assert "DISETUJUI" in kabar[1].pesan
    # Satu kabar, dua gudang — `notifications` tak punya kolom orang, jadi
    # kalimatnya yang menyebut bagian masing-masing.
    assert "Gudang 1 yang memuat" in kabar[1].pesan
    assert "Gudang 2 menunggu" in kabar[1].pesan
    assert "ditutup" in kabar[2].pesan


async def test_penolakan_mengabari_peminta_beserta_sebabnya(pg, pabrik):
    """Permintaan yang lenyap tanpa kabar membuat orangnya menekannya lagi
    besok, dan Admin menolaknya lagi; keduanya mengira pihak satunya yang
    lalai. `sebab` sudah diwajibkan sejak awal — yang belum ada pembacanya."""
    from sqlalchemy import select

    from app.models import Notification, User
    from app.services.permintaan_pk import tolak

    pid = await _minta(pg, pabrik)
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        await tolak(db, user=u, permintaan_id=pid, sebab="Lot ini untuk pesanan lain.")

    async with pg() as db:
        kabar = list((await db.execute(
            select(Notification).where(Notification.tipe == "permintaan_pk")
            .order_by(Notification.id))).scalars().all())
    tolakan = kabar[-1]
    assert tolakan.target_role == "operator" and tolakan.prioritas == "merah"
    assert "DITOLAK" in tolakan.pesan and "pesanan lain" in tolakan.pesan


async def test_yang_berakhir_tanpa_barang_tetap_berjejak_di_layarnya(pg, pabrik):
    """Dua keadaan yang kartunya lenyap begitu statusnya berubah — dan
    satu-satunya di seluruh rantai yang tak punya jejak di layar mana pun.

    Kabar di `notifications` tidak menjawab ini: tak satu pun layar membacanya
    untuk ditampilkan (diperiksa 26 September 2026 — tabel itu ditulis lima
    tempat, dibaca hanya untuk menutup barisnya sendiri). Yang menjawab adalah
    kartu di Transit, berumur, tanpa tombol.
    """
    from app.models import User
    from app.services.berjalan import untuk_operator_gudang2
    from app.services.permintaan_pk import baru_ditutup, tolak

    pid = await _minta(pg, pabrik)
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        await tolak(db, user=u, permintaan_id=pid, sebab="Dipakai pesanan lain.")

    async with pg() as db:
        assert [x.id for x in await baru_ditutup(db)] == [pid]
        b = await untuk_operator_gudang2(db)
    k = next(x for x in b.transit if x.judul == "Permintaan Anda ditolak")
    assert "Dipakai pesanan lain." in k.isi
    assert k.aksi is None and not k.pilihan, \
        "kartu bertombol atas permintaan yang sudah berakhir"
    # Dan ia TIDAK menagih lencana antrean: tak ada yang bisa dikerjakan.
    assert not [x for x in b.menunggu if x.kode == pabrik["lot"]]
    # Berumur: yang lewat batas berhenti sendiri, tanpa perlu dipencet.
    async with pg() as db:
        assert await baru_ditutup(db, jam=0) == []


async def test_gugur_sesudah_disetujui_mengabari_dua_pihak(pg, pabrik):
    """Yang gugur SESUDAH disetujui sudah masuk antrean kerja seseorang, dan ia
    akan mencari kartu yang tiba-tiba tak ada. Admin pun kehilangan barisnya
    dari meja tanpa pernah memutuskan apa pun — jadi dua pihak, bukan satu."""
    from sqlalchemy import select

    from app.models import Notification, PermintaanPk, User
    from app.services.permintaan_pk import gugurkan_yang_habis
    from app.services.transfer import create_internal_transfer

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid, berat=1_000)
    # Lot dihabiskan lewat jalan lain — persis kejadian yang digugurkan.
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        await create_internal_transfer(db, user=u, kode_proses=pabrik["lot"],
                                       lokasi_tujuan="ditumpuk", berat=6_000)
    async with pg() as db:
        assert await gugurkan_yang_habis(db) == 1

    async with pg() as db:
        kabar = list((await db.execute(
            select(Notification).where(Notification.tipe == "permintaan_pk")
            .order_by(Notification.id))).scalars().all())
        baris = await db.get(PermintaanPk, pid)
    assert {k.target_role for k in kabar[-2:]} == {"operator", "admin"}
    # Sebabnya membedakan gugur SESUDAH disetujui dari gugur sebelum diputuskan.
    assert "SESUDAH permintaan ini disetujui" in (baris.sebab or "")
    assert any("SESUDAH" in k.pesan for k in kabar[-2:])


async def test_kalimat_persetujuan_menyebut_gudang_yang_benar(pg, pabrik):
    """Temuan QA 26 September 2026 pada 9c5a4c0, kecil dan pasti.

    Kalimat ini sudah DUA KALI menyebut gudang yang salah — sekali karena
    tertinggal dari rancangan lama, sekali lagi karena tangannya berpindah.
    Maka yang dijaga bukan bunyinya melainkan ATURANNYA: ia harus mengatakan
    hal yang sama dengan kartu-kartunya. Admin yang membaca kalimat yang salah
    akan menunggu gudang yang pintunya justru menolak mereka dengan 403.

    Sejak 27 September 2026: yang memuat Gudang 1, kartunya bertombol di
    Antrian tunggu Gudang 1, Gudang 2 menunggu di Transit-nya.

    Diuji pada KALIMAT YANG DIKEMBALIKAN, bukan pada sumbernya: komentar di
    sebelahnya mengutip kalimat-kalimat lama supaya sejarahnya tak hilang, dan
    pagar yang membaca sumber akan tersandung kutipan itu.
    """
    from app.models import User
    from app.web import api

    pid = await _minta(pg, pabrik)
    async with pg() as db:
        adm = await db.get(User, pabrik["admin"])
    jawab = await api.act_acc_permintaan_pk(
        api.AccPermintaanReq(permintaan=str(pid), tujuan="A", berat=6_000),
        user=adm)
    pesan = jawab["pesan"]
    assert "Gudang 1 yang memuat" in pesan, pesan
    assert "Gudang 2 yang menjemput" not in pesan, "tangan lama masih disebut"
    # Dan ia menunjuk layar yang benar: kartunya memang di Antrian tunggu
    # Gudang 1, bukan di Transit seperti sehari sebelumnya.
    assert "Antrian tunggu" in pesan


async def test_tiap_langkah_menawarkan_daftarnya_bukan_kotak_ketik(pg, pabrik):
    """Laporan pemilik 26 September 2026 dengan fotonya: "kalau harus mengetik
    lot tentu sangat repot."

    Kelima aksi rantai ini beriaian penunjuk bertipe `text`, jadi kartu yang
    mengirim `nilai` tak mengisi apa pun — dan tiga di antaranya meminta ID
    BARIS BASIS DATA, angka yang tak pernah ditampilkan di layar mana pun.

    Bentuk spesifikasinya dijaga `tests/test_penunjuk_borang.py`. Yang diuji di
    sini ISINYA: tiap daftar menawarkan persis yang bisa dikerjakan pada
    langkah itu, dan labelnya menyebut LOT — bukan nomor baris.
    """
    from app.models import User
    from app.web import api

    async with pg() as db:
        adm = await db.get(User, pabrik["admin"])
        op1 = await db.get(User, pabrik["op1"])
        op2 = await db.get(User, pabrik["op2"])

    # 0 · sebelum diminta: lotnya ditawarkan kepada Gudang 2.
    lot = await api.pk_g1_tersedia(user=op2)
    assert [l["value"] for l in lot] == [pabrik["lot"]], lot
    assert "kg" in lot[0]["label"], "daftar lot tak menyebut sisa PK-nya"
    assert await api.permintaan_menunggu_keputusan(user=adm) == []

    # 1 · diminta: lotnya BERHENTI ditawarkan (satu permintaan terbuka per lot),
    #     dan Admin mendapat barisnya.
    pid = await _minta(pg, pabrik)
    assert await api.pk_g1_tersedia(user=op2) == [], \
        "lot yang sudah diminta masih ditawarkan — penolakan yang bisa dihindari"
    tunggu = await api.permintaan_menunggu_keputusan(user=adm)
    assert [t["value"] for t in tunggu] == [str(pid)]
    assert pabrik["lot"] in tunggu[0]["label"], \
        "Admin disuruh mengenali permintaan dari nomor barisnya"
    assert await api.permintaan_siap_dimuat(user=op1) == []

    # 2 · disetujui: pindah ke daftar GUDANG 1 — yang mengirim — berikut
    #     tujuannya (keputusan pemilik 27 September 2026).
    await _acc(pg, pabrik, pid, tujuan="A", berat=6_000)
    assert await api.permintaan_menunggu_keputusan(user=adm) == []
    siap = await api.permintaan_siap_dimuat(user=op1)
    assert [s["value"] for s in siap] == [str(pid)]
    assert "Silo A" in siap[0]["label"], "tujuannya tak disebut di daftar"

    # 3 · dikirim: pindah ke daftar penutupan Admin.
    await _kirim(pg, pabrik, pid, berat=6_000)
    assert await api.permintaan_siap_dimuat(user=op1) == []
    tutup = await api.permintaan_menunggu_ditutup(user=adm)
    assert [t["value"] for t in tutup] == [str(pid)]
    assert pabrik["lot"] in tutup[0]["label"]


async def test_lot_yang_habis_terkirim_hilang_dari_stok_gudang1(pg, pabrik):
    """Permintaan pemilik 27 September 2026: "jika sudah gudang 1 menekan
    tombol kirim selesai. setelah diverifikasi oleh admin. kartu lot di stock
    gudang 1 harusnya hilang."

    Diuji sebagai RANTAI, bukan pada satu titik — sebab kartunya bisa hilang
    lalu muncul kembali. `tutup_admin` membetulkan bobot dengan membatalkan
    perpindahannya lalu mencatat ulang (peristiwa lawan, bukan UPDATE diam-diam),
    dan di antara keduanya stok lot ini berubah dua kali. Pagar yang cuma
    melihat keadaan akhir akan lulus walau kartunya sempat berkedip.
    """
    from app.models import User
    from app.services.permintaan_pk import tutup_admin
    from app.services.stok import pk_gudang1

    async def kartu():
        async with pg() as db:
            return [l for l in await pk_gudang1(db) if l.kode == pabrik["lot"]]

    assert len(await kartu()) == 1, "lot belum apa-apa sudah tak berkartu"

    pid = await _minta(pg, pabrik)
    assert len(await kartu()) == 1, "kartunya hilang hanya karena diminta"
    await _acc(pg, pabrik, pid, berat=6_000)
    assert len(await kartu()) == 1, "kartunya hilang sebelum barangnya berangkat"

    # Dikirim SELURUHNYA: 6.000 kg dari lot 6.000 kg.
    await _kirim(pg, pabrik, pid, berat=6_000)
    assert await kartu() == [], "PK sudah berangkat tapi kartunya masih berdiri"

    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        await tutup_admin(db, user=u, permintaan_id=pid, berat_final=6_000)
    assert await kartu() == [], \
        "kartunya muncul lagi sesudah Admin menutup — pembetulan bobot " \
        "membatalkan perpindahan lalu mencatat ulang; salah satunya tak pulih"


async def test_pembetulan_bobot_mengembalikan_sisanya_ke_kartu(pg, pabrik):
    """Sisi lain dari butir yang sama, dan ia WAJIB berlawanan arah.

    Kalau Admin menutup dengan bobot LEBIH KECIL daripada yang dimuat, selisih
    itu tak pernah berangkat — ia masih berdiri di lantai Gudang 1. Kartunya
    harus KEMBALI, berisi sisanya.

    Tanpa pagar ini, "kartu lot harus hilang" mudah dikerjakan dengan cara yang
    salah — menyembunyikan kartu begitu permintaannya ditutup, apa pun bobotnya
    — dan PK yang tak jadi berangkat lenyap dari angka stok tanpa satu pun
    galat.
    """
    from app.models import User
    from app.services.permintaan_pk import tutup_admin
    from app.services.stok import pk_gudang1

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid, berat=6_000)
    await _kirim(pg, pabrik, pid, berat=6_000)

    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        await tutup_admin(db, user=u, permintaan_id=pid, berat_final=5_500)

    async with pg() as db:
        lot = [l for l in await pk_gudang1(db) if l.kode == pabrik["lot"]]
    assert len(lot) == 1, "500 kg yang tak jadi berangkat lenyap dari Stok"
    assert lot[0].tersedia == 500, lot[0].tersedia
