"""Cakupan pembatalan ditentukan dari CATATAN, bukan dari orangnya hari ini.

Temuan QA putaran 4, P4-02 (KRITIS). `resolve_actor_ids` menjawab "siapa saja
operator Gudang 1" dengan membaca `users.default_warehouse_id` — gudang yang
DIPEGANG SEKARANG. Padahal pembatalan massal bertanya tentang MASA LALU:
siapa yang mencatat di Gudang 1. Sejak operator boleh berpindah gudang untuk
saling menggantikan (13 Sep 2026), kedua pertanyaan itu berbeda jawabannya:
pada hari operator menggantikan rekannya di Gudang 2, cakupan "operator
Gudang 1" berhenti mengenai catatan lamanya, dan cakupan "operator Gudang 2"
ikut menyapu seluruh pekerjaannya di Gudang 1 — gudang lain, hari lain.

Sekarang tiap baris `activity_logs` membawa gudangnya sendiri (`gudang`),
diisi saat pencatatan dari tabel yang dicatat — sebuah gabah masuk adalah
urusan Gudang 1 apa pun yang tertulis di profil pencatatnya. Cakupan gudang
membaca kolom itu; baris yang tak punya gudang tak pernah tersapu cakupan
gudang mana pun.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def dua_gudang(pg):
    from app.models import Warehouse

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add_all([g1, g2])
        await db.commit()
        return g1.id, g2.id


@pytest.fixture
async def operator(pg, dua_gudang):
    """Operator yang HARI INI tercatat di Gudang 1."""
    from app.models import User

    async with pg() as db:
        u = User(nama="Operator Uji", role="operator", status="aktif",
                 default_warehouse_id=dua_gudang[0])
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


async def _pindahkan(pg, user_id: int, gudang_id: int) -> None:
    """Admin memindahkan operator untuk menggantikan rekan — hanya profilnya."""
    from app.models import User

    async with pg() as db:
        u = await db.get(User, user_id)
        u.default_warehouse_id = gudang_id
        await db.commit()


async def _terakhir(pg, scope: str, self_id: int = 0):
    from app.services import undo as svc

    async with pg() as db:
        c = await svc.cakupan(db, scope=scope, nama=None, self_id=self_id)
        p = await svc.pratinjau_terakhir(db, cakupan=c)
        return p.log_id if p is not None else None


async def test_pindah_gudang_tidak_mengubah_cakupan_catatan_lama(pg, dua_gudang, operator):
    """Catatan di Gudang 1 tetap milik cakupan Gudang 1 walau orangnya sudah
    dipindah ke Gudang 2 — dan TIDAK ikut masuk cakupan Gudang 2."""
    from app.models import ActivityLog
    from app.services.activity_log import log_activity

    async with pg() as db:
        await log_activity(db, table_name="purchase_batches", record_id=1,
                           action="INSERT", changed_by=operator.id,
                           new_value="gabah masuk di G1")
        await db.commit()
        log_g1 = (await db.execute(select(ActivityLog.id))).scalars().first()

    assert await _terakhir(pg, "operator_gudang1") == log_g1
    assert await _terakhir(pg, "operator_gudang2") is None

    await _pindahkan(pg, operator.id, dua_gudang[1])

    # Hari menggantikan: jawabannya HARUS sama — tak satu baris riwayat pun disentuh.
    assert await _terakhir(pg, "operator_gudang1") == log_g1
    assert await _terakhir(pg, "operator_gudang2") is None


async def test_catatan_di_dua_gudang_masing_masing_masuk_cakupannya(pg, dua_gudang, operator):
    """Mencatat di G1, dipindah ke G2, mencatat lagi di G2: tiap cakupan hanya
    memuat catatan yang gudangnya sesuai."""
    from app.models import ActivityLog
    from app.services.activity_log import log_activity

    async with pg() as db:
        await log_activity(db, table_name="purchase_batches", record_id=1,
                           action="INSERT", changed_by=operator.id, new_value="di G1")
        await db.commit()
    await _pindahkan(pg, operator.id, dua_gudang[1])
    async with pg() as db:
        await log_activity(db, table_name="pk_gudang2_intakes", record_id=1,
                           action="INSERT", changed_by=operator.id, new_value="di G2")
        await db.commit()
        ids = (await db.execute(
            select(ActivityLog.id).order_by(ActivityLog.id))).scalars().all()
    log_g1, log_g2 = ids

    assert await _terakhir(pg, "operator_gudang1") == log_g1
    assert await _terakhir(pg, "operator_gudang2") == log_g2
    # Dan cakupan tanpa gudang melihat yang paling akhir, apa pun gudangnya.
    assert await _terakhir(pg, "semua") == log_g2
    assert await _terakhir(pg, "saya", self_id=operator.id) == log_g2


async def test_baris_tanpa_gudang_tak_pernah_tersapu_cakupan_gudang(pg, dua_gudang, operator):
    """Baris lama (sebelum kolom ada) dan baris yang memang bukan milik gudang
    mana pun masuk kategori 'tak diketahui': cakupan gudang melewatinya."""
    from app.models import ActivityLog
    from app.services.activity_log import log_activity

    async with pg() as db:
        await log_activity(db, table_name="purchase_batches", record_id=1,
                           action="INSERT", changed_by=operator.id, new_value="di G1")
        await db.commit()
        log_g1 = (await db.execute(select(ActivityLog.id))).scalars().first()
        # Baris "lama": tabelnya bisa dibatalkan, tetapi gudangnya tak tercatat.
        db.add(ActivityLog(table_name="silo_storage", record_id=9, action="INSERT",
                           changed_by=operator.id, new_value="baris warisan", gudang=None))
        await db.commit()
        tanpa = (await db.execute(
            select(ActivityLog.id).order_by(ActivityLog.id.desc()))).scalars().first()
    assert tanpa != log_g1

    assert await _terakhir(pg, "operator_gudang1") == log_g1
    assert await _terakhir(pg, "operator_gudang2") is None
    # Cakupan yang tak bertanya soal gudang tetap melihatnya.
    assert await _terakhir(pg, "semua") == tanpa


async def test_pencatat_menyimpulkan_gudang_dari_tabelnya(pg, operator, hitung_kueri):
    """Gudang diisi oleh pencatat dari tabel yang dicatat — tanpa satu kueri pun,
    karena ia ikut transaksi 51 pemanggilnya dan tak boleh mengubah perilaku
    satu pun. Pemanggil yang tahu lebih baik boleh menyebutnya sendiri."""
    from app.models import ActivityLog
    from app.services.activity_log import log_activity

    async with pg() as db:
        async with hitung_kueri() as n:
            await log_activity(db, table_name="purchase_batches", record_id=1,
                               action="INSERT", changed_by=operator.id)
            await log_activity(db, table_name="pk_gudang2_intakes", record_id=1,
                               action="INSERT", changed_by=operator.id)
            await log_activity(db, table_name="outgoing_records", record_id=1,
                               action="INSERT", changed_by=operator.id, gudang="g1")
            await log_activity(db, table_name="setelan_pabrik", record_id=0,
                               action="UPDATE", changed_by=operator.id)
        assert n.jumlah == 0, n.perintah
        await db.commit()
        baris = (await db.execute(
            select(ActivityLog.table_name, ActivityLog.gudang).order_by(ActivityLog.id)
        )).all()
    assert baris == [("purchase_batches", "g1"), ("pk_gudang2_intakes", "g2"),
                     ("outgoing_records", "g1"), ("setelan_pabrik", None)]


async def test_tiap_tabel_yang_bisa_dibatalkan_punya_gudang():
    """Kalau ada tabel yang bisa dibatalkan tetapi gudangnya tak dikenal, catatan
    barunya jatuh ke 'tak diketahui' dan cakupan gudang tak pernah melihatnya —
    kesalahan yang diam. Kecuali yang memang melintasi gudang."""
    from app.services import undo as svc
    from app.services.activity_log import GUDANG_TABEL

    for tabel in svc._UNDOABLE:
        assert tabel in GUDANG_TABEL, f"{tabel} belum punya gudang"
