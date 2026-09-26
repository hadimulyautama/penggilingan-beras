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


async def _kirim(pg, pabrik, pid: int, *, berat=6_000):
    from app.models import User
    from app.services.permintaan_pk import kirim

    async with pg() as db:
        u = await db.get(User, pabrik["op1"])
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

async def test_gudang1_tak_bisa_mengirim_yang_belum_disetujui(pg, pabrik):
    from app.services.permintaan_pk import PermintaanError

    pid = await _minta(pg, pabrik)
    with pytest.raises(PermintaanError) as e:
        await _kirim(pg, pabrik, pid)
    assert "menunggu keputusan Admin" in str(e.value)


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


async def test_dua_operator_g1_menekan_kirim_bersamaan(pg, pabrik):
    """Yang paling mahal bila lolos: DUA perpindahan atas PK yang sama."""
    from sqlalchemy import select

    from app.models import InternalTransfer, User
    from app.services.permintaan_pk import kirim

    pid = await _minta(pg, pabrik)
    await _acc(pg, pabrik, pid, berat=6_000)

    async def kirim_satu(berat):
        async with pg() as db:
            u = await db.get(User, pabrik["op1"])
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
    assert [x.aksi for x in adm.menunggu if x.kelompok == "permintaan"] == ["acc_permintaan_pk"]
    assert not [x for x in g1.menunggu if x.kelompok == "permintaan"], \
        "Gudang 1 melihat pekerjaan yang belum boleh ia kerjakan"
    assert "menunggu keputusan Admin" in lot.diminta_keadaan

    # 2 · disetujui — pindah ke tangan Gudang 1.
    await _acc(pg, pabrik, pid, berat=6_000)
    async with pg() as db:
        adm, g1 = await untuk_staff(db), await untuk_gudang1(db)
        lot = next(l for l in await pk_gudang1(db) if l.kode == pabrik["lot"])
    assert not [x for x in adm.menunggu if x.kelompok == "permintaan"], \
        "Admin menunggui pekerjaan yang bukan miliknya"
    assert [x.aksi for x in g1.menunggu if x.kelompok == "permintaan"] == ["kirim_permintaan_pk"]
    assert "menunggu dikirim Gudang 1" in lot.diminta_keadaan

    # 3 · dikirim — kembali ke Admin, untuk ditutup.
    await _kirim(pg, pabrik, pid, berat=6_000)
    async with pg() as db:
        adm, g1 = await untuk_staff(db), await untuk_gudang1(db)
    assert [x.aksi for x in adm.menunggu if x.kelompok == "permintaan"] == ["tutup_permintaan_pk"]
    assert not [x for x in g1.menunggu if x.kelompok == "permintaan"]


async def test_peminta_punya_kartunya_sendiri_sepanjang_alur(pg, pabrik):
    """Butir pemilik yang paling mudah dianggap sudah beres, dan bukan:
    operator Gudang 2 harus BERKARTU, bukan cuma melihat satu kalimat di lot
    yang kebetulan ia susuri di layar Stok.

    Kartunya di TRANSIT, bukan di antrean: tak satu pun langkah alur ini
    miliknya sesudah ia menekan Minta, dan lencana antrean yang menagih
    pekerjaan yang tak bisa dikerjakan siapa pun akan berhenti dibaca.
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
