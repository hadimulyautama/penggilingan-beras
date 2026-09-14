"""Undo membatalkan PERSIS yang tertulis di layar — dan tak merusak milik orang.

Lima temuan QA 11 September 2026, semuanya di jalur "Batalkan input terakhir".

**P-K-09.** Layar menampilkan pratinjau, tetapi yang dikirim saat menekan
hanya LINGKUP-nya. Saat mengeksekusi, `undo_last` mencari "aksi terakhir" lagi
— dan bila ada aksi lain masuk di antara melihat dan menekan, yang dibatalkan
adalah aksi itu. Orang membaca satu kalimat dan membatalkan kalimat yang lain.

**P-K-21.** Pembatalan MENGHAPUS baris jejak auditnya. Jejak audit bersifat
tambah-saja (ARSITEKTUR §6): ia satu-satunya catatan siapa mengerjakan apa,
dan menghapusnya menghapus bukti pada saat bukti paling dibutuhkan.

**P-K-08.** `silo.py` mencatat `record_id` = id SILO, bukan id baris
`silo_storage`. Pembatalan lalu mengambil baris TERBARU di silo itu — jadi
Budi membatalkan entri Sari.

**P-K-02.** Semua UPDATE `drying_lots` yang bukan status dikirim ke
`_undo_lot_merge`, yang mengeluarkan batch terakhir dari lot. Membatalkan
"ubah target kadar air" justru mengeluarkan gabah dari lot yang sedang
dikeringkan, dan targetnya tak kembali.
"""
from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.asyncio


async def test_undo_membawa_id_log_yang_ditampilkan(pg):
    """Yang dikirim harus MENUNJUK aksinya, bukan sekadar lingkupnya."""
    from app.services import undo as svc
    from app.web import aksi_undo

    assert "log_id" in inspect.signature(svc.undo_last).parameters
    # Pratinjau ikut membawa id-nya, kalau tidak layar tak punya apa yang
    # harus dikirim.
    assert "log_id" in {f.name for f in svc.Pratinjau.__dataclass_fields__.values()}
    # Dan daftar pilihannya menaruh id itu di nilainya.
    kode = inspect.getsource(aksi_undo.undo_terakhir)
    assert "log_id" in kode


async def test_undo_menolak_bila_ada_aksi_baru_menyusul(pg, pemakai, pemasok):
    """Skenario P-K-09: Sari mencatat sesuatu antara Budi melihat dan menekan."""
    from app.services import undo as svc
    from app.services.activity_log import log_activity

    async with pg() as db:
        await log_activity(db, table_name="purchase_batches", record_id=1,
                           action="INSERT", changed_by=pemakai.id,
                           new_value="punya Budi")
        await db.commit()
        p = await svc.pratinjau_terakhir(db, cakupan=None)
        assert p is not None
        lama = p.log_id

        # Sari mencatat sesudahnya.
        await log_activity(db, table_name="purchase_batches", record_id=2,
                           action="INSERT", changed_by=pemakai.id,
                           new_value="punya Sari")
        await db.commit()

        with pytest.raises(svc.UndoError) as e:
            await svc.undo_last(db, actor=pemakai, cakupan=None,
                                log_id=lama)
    assert "berubah" in str(e.value).lower() or "bukan" in str(e.value).lower()


async def test_jejak_audit_ditandai_bukan_dihapus(pg, pemakai, pemasok):
    """P-K-21 & ARSITEKTUR §6: jejak audit tambah-saja."""
    from sqlalchemy import select

    from app.models import ActivityLog
    from app.services import undo as svc
    from app.services.activity_log import log_activity

    async with pg() as db:
        await log_activity(db, table_name="drying_moisture_logs", record_id=1,
                           action="INSERT", changed_by=pemakai.id,
                           new_value="uji")
        await db.commit()
        p = await svc.pratinjau_terakhir(db, cakupan=None)
        sebelum = (await db.execute(select(ActivityLog))).scalars().all()
        jumlah = len(sebelum)

        try:
            await svc.undo_last(db, actor=pemakai, cakupan=None,
                                log_id=p.log_id)
        except svc.UndoError:
            pass          # gagal membatalkan pun tak boleh menghapus jejak

        sesudah = (await db.execute(select(ActivityLog))).scalars().all()
    assert len(sesudah) >= jumlah, "baris jejak audit HILANG"


async def test_dispatch_undo_dari_tag_bukan_tebakan():
    """P-K-02. Dispatch menebak dari nama tabel & kolom, jadi dua aksi yang
    berbeda maksudnya jatuh ke penangan yang sama."""
    from app.services import undo as svc

    kode = inspect.getsource(svc._undo_one)
    # Tag dibaca LEBIH DULU, sebelum satu pun tebakan dari nama tabel.
    assert '"aksi"' in kode or "log.aksi" in kode, (
        "dispatch belum memakai tag aksi eksplisit")
    assert kode.index("tag") < kode.index("log.table_name")
    # Dan tag yang dikenal memang menunjuk penangan yang berbeda-beda.
    assert len(set(svc._PENANGAN_TAG.values())) == len(svc._PENANGAN_TAG)


async def test_silo_mencatat_id_baris_bukan_id_silo():
    """P-K-08. `record_id` = id SILO membuat pembatalan mengambil baris
    TERBARU di silo itu — milik siapa pun yang terakhir mengisi."""
    from app.penggilingan.gudang1.services import silo

    kode = inspect.getsource(silo)
    # Yang dicatat id baris penyimpanan, bukan id silonya.
    assert "record_id=storage.id" in kode or "record_id=baris.id" in kode


async def test_ubah_target_tak_mengeluarkan_batch_dari_lot():
    """P-K-02, gejalanya. Pratinjau berkata "lot pengeringan · 13.0",
    hasilnya GB-02 keluar dari lot dan targetnya tak kembali."""
    from app.penggilingan.gudang1.services import drying

    kode = inspect.getsource(drying.ubah_target)
    assert 'aksi="ubah_target"' in kode, "aksinya tak ditandai"


async def test_aksi_satu_ketuk_menawarkan_batalkan(pg):
    """UI-03. "Ke Silo A" menyimpan tanpa konfirmasi — dan itu memang gunanya:
    operator memegang telepon satu tangan sambil mengarahkan truk. Dialog
    "yakin?" akan membayar kecepatan itu dengan ketukan yang sama seringnya.

    Yang ditambahkan jalan MUNDUR-nya: kabar "Tersimpan" membawa tombol
    BATALKAN selama delapan detik, dan tombol itu membatalkan catatan yang
    barusan dibuat — id-nya dari jawaban server, bukan dicari ulang sebagai
    "yang terakhir".
    """
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[2]
          / "hmu_tampilan/static/aksi.js").read_text()
    assert "kabarBisaBatal" in js
    assert "BATALKAN" in js
    # Delapan detik, bukan 2,6 seperti kabar biasa.
    blok = js[js.index("function kabarBisaBatal"):js.index("function kabarBisaBatal") + 2000]
    assert "8000" in blok
    # Dan id-nya datang dari jawaban server.
    assert "hasil.log_id" in js
    assert '"saya:" + logId' in js


async def test_endpoint_satu_ketuk_menyebut_id_jejaknya():
    """Tanpa id, tombol BATALKAN kembali jadi "batalkan yang terakhir" — dan
    di antara menekan dan membatalkan, rekan di pos sebelah bisa saja sudah
    mencatat sesuatu."""
    import inspect

    from app.web import miniapp

    for fn in (miniapp.act_gabah_masuk, miniapp.act_tempatkan_gabah):
        assert "_id_jejak(" in inspect.getsource(fn), fn.__name__
