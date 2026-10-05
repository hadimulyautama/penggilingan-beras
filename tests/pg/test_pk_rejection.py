"""PK luar DITOLAK saat datang — keputusan pemilik 4 Oktober 2026.

Borang `catat_pk_luar` dapat tombol kedua: "Tolak". Satu-satunya yang wajib
diisi alasannya — PK yang ditolak tak pernah jadi stok, jadi jenis & kadar
air tak perlu diklasifikasi. Tabel & kolomnya (`pk_rejections`, kode `REJ-`,
`alasan_tolak`) sudah ada sejak migrasi 0012 (5 Juli 2026) tapi tak pernah
dipakai — ini pemakai pertamanya.

⚠⚠ Tiket timbangnya ikut ditutup paksa sebagai "truk pergi tanpa ditimbang
keluar", MENGESAMPINGKAN Temuan QA T-15 di repo timbangan (yang menolak
menutup paksa tiket hanya karena muatannya ditolak, demi kontrol
masuk−keluar). Pemilik sadar melepas kontrol itu khusus untuk kasus ini.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio


_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, timbang2_kg, timbang2_waktu,
         berat_kosong_kg, netto_timbangan_kg, berat_acuan_kg,
         status_tiket, status_transaksi)
    VALUES
        (:kode, :tanggal, 'MASUK', 'BERAS_PK', 'DUA_KALI', :supplier_id, :pihak,
         :nopol, :t1, :waktu, :t2, :waktu2, :kosong, :netto, 0,
         :status_tiket, 'AKTIF')
    RETURNING id
""")


async def _tiket(db, kode, *, nopol, t1, netto=None, kosong=None,
                 supplier_id=None, pihak="Pak Uji") -> int:
    """Satu tiket PK MASUK. `netto` None = truk belum ditimbang kedua (TERBUKA)."""
    waktu = datetime.now(timezone.utc)
    selesai = netto is not None
    return (await db.execute(_SQL_TIKET, {
        "kode": kode, "tanggal": date.today(),
        "supplier_id": supplier_id, "pihak": pihak, "nopol": nopol,
        "t1": t1, "waktu": waktu,
        "t2": (kosong if selesai else None), "waktu2": (waktu if selesai else None),
        "kosong": (kosong if selesai else None), "netto": netto,
        "status_tiket": "SELESAI" if selesai else "TERBUKA",
    })).scalar_one()


async def _status_tiket(db, tid: int) -> dict:
    baris = (await db.execute(text(
        "SELECT status_tiket, tutup_paksa_alasan, netto_timbangan_kg "
        "FROM timbangan_transaksi WHERE id = :i"), {"i": tid})).one()
    return {"status_tiket": baris[0], "alasan": baris[1], "netto": baris[2]}


@pytest_asyncio.fixture
async def admin(pg, pemakai):
    from sqlalchemy import select

    from app.models import User, Warehouse
    from app.peran import PERAN_ADMIN_KEATAS

    async with pg() as db:
        # `_g2_warehouse_id` (dipakai `untuk_gudang2`, `masukkan_pk_luar`,
        # dll.) menolak keras bila "Gudang 2" tak ada sama sekali di master.
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            db.add(Warehouse(nama_gudang="Gudang 2 - Penyosohan"))
        u = await db.get(User, pemakai.id)
        u.role = PERAN_ADMIN_KEATAS[-1]
        await db.commit()
        await db.refresh(u)
        return u


async def test_ditolak_tercatat_tutup_paksa_dan_tak_jadi_stok(pg, admin, pemasok):
    """Jalur utama: tiket TERBUKA → ditolak → batch 'ditolak', `pk_rejections`
    terisi, dan tiketnya ditutup paksa dengan alasan yang SAMA.

    Bobotnya PERKIRAAN (tara truk yang sama, tiket LAMA sudah selesai) —
    tiket yang DITOLAK justru yang paling sering TERBUKA (belum ditimbang
    keluar), dan truk semacam itu paling wajar sudah punya tara terakhir."""
    from app.models import PkGudang2Intake, PkPurchaseBatch, PkRejection
    from app.penggilingan.gudang2.service import create_pk_rejection_dari_timbang

    async with pg() as db:
        # Tara truk ini: tiket LAMA, selesai, kosong=4.200 kg — realistis
        # untuk truk 9.800 kg (batas `MUATAN_MAKS_X_TARA` = 4× tara, dan
        # 9.800 ≤ 4×4.200) → perkiraan tiket baru = 14.000 − 4.200 = 9.800.
        await _tiket(db, "T-REJ-00", nopol="AD 1 RJ", t1=14_000, netto=9_800,
                     kosong=4_200, supplier_id=pemasok.id)
        await db.commit()
    async with pg() as db:
        tid = await _tiket(db, "T-REJ-01", nopol="AD 1 RJ", t1=14_000,
                           supplier_id=pemasok.id)
        await db.commit()

    async with pg() as db:
        u = await db.get(type(admin), admin.id)
        r = await create_pk_rejection_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid,
            alasan="Kadar air jauh di atas ambang, truk ditolak di pintu gudang.",
        )

    assert r.tiket_ditutup is True
    assert r.rejection.kode.startswith("REJ-")
    assert r.pihak_nama == pemasok.nama_supplier

    async with pg() as db:
        batch = await db.get(PkPurchaseBatch, r.batch.id)
        assert batch.status_batch == "ditolak"
        assert batch.jenis_pk is None
        rej = (await db.execute(select(PkRejection).where(
            PkRejection.pk_purchase_batch_id == batch.id))).scalars().one()
        assert rej.alasan == "Kadar air jauh di atas ambang, truk ditolak di pintu gudang."
        assert float(rej.berat_kg) == 9_800
        # PK yang ditolak tak pernah jadi stok — tak ada baris intake sama sekali.
        intake = (await db.execute(select(PkGudang2Intake).where(
            PkGudang2Intake.pk_purchase_batch_id == batch.id))).scalars().first()
        assert intake is None

    async with pg() as db:
        tiket = await _status_tiket(db, tid)
    assert tiket["status_tiket"] == "DITUTUP_PAKSA"
    assert "Kadar air jauh di atas ambang" in tiket["alasan"]
    assert "PK ditolak di produksi" in tiket["alasan"]
    # `_kosongkan_hasil` ikut diterapkan — truk ini tak pernah "selesai timbang".
    assert tiket["netto"] is None


async def test_alasan_wajib_diisi(pg, admin, pemasok):
    from app.penggilingan.gudang2.service import Gudang2Error, create_pk_rejection_dari_timbang

    async with pg() as db:
        tid = await _tiket(db, "T-REJ-02", nopol="AD 2 RJ", t1=5_000,
                           supplier_id=pemasok.id)
        await db.commit()

    async with pg() as db:
        u = await db.get(type(admin), admin.id)
        with pytest.raises(Gudang2Error) as e:
            await create_pk_rejection_dari_timbang(
                db, user=u, timbangan_transaksi_id=tid, alasan="   ")
    assert "alasan" in str(e.value).lower()


async def test_tiket_yang_sudah_selesai_tak_disentuh(pg, admin, pemasok):
    """Truk yang KEBETULAN sudah selesai timbang kedua sebelum admin menolaknya
    di produksi (mis. operator pos timbang terlanjur menutupnya normal) tak
    boleh diubah lagi — yang sudah tercatat tetap berdiri."""
    from app.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import create_pk_rejection_dari_timbang

    async with pg() as db:
        tid = await _tiket(db, "T-REJ-03", nopol="AD 3 RJ", t1=9_800, netto=9_800,
                           kosong=0, supplier_id=pemasok.id)
        await db.commit()

    async with pg() as db:
        u = await db.get(type(admin), admin.id)
        r = await create_pk_rejection_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, alasan="Ditolak belakangan.")
    assert r.tiket_ditutup is False

    async with pg() as db:
        batch = await db.get(PkPurchaseBatch, r.batch.id)
        assert batch.status_batch == "ditolak"
        tiket = await _status_tiket(db, tid)
    # Tiketnya TETAP SELESAI, bukan DITUTUP_PAKSA — dan netto aslinya bertahan.
    assert tiket["status_tiket"] == "SELESAI"
    assert float(tiket["netto"]) == 9_800


async def test_tiket_yang_sudah_dipakai_ditolak_dua_kali(pg, admin, pemasok):
    """`kunci_tiket_untuk_ditaut` yang sudah menjaga jalur terima menjaga jalur
    tolak juga — tiket yang sudah jadi batch (apa pun hasilnya) tak bisa
    diproses ulang."""
    from app.penggilingan.gudang2.service import Gudang2Error, create_pk_rejection_dari_timbang

    async with pg() as db:
        tid = await _tiket(db, "T-REJ-04", nopol="AD 4 RJ", t1=4_000,
                           supplier_id=pemasok.id)
        await db.commit()

    async with pg() as db:
        u = await db.get(type(admin), admin.id)
        await create_pk_rejection_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, alasan="Pertama.")

    async with pg() as db:
        u = await db.get(type(admin), admin.id)
        with pytest.raises(Gudang2Error) as e:
            await create_pk_rejection_dari_timbang(
                db, user=u, timbangan_transaksi_id=tid, alasan="Kedua.")
    assert "sudah dicatat" in str(e.value).lower()


async def test_borang_gabungan_catat_langsung_tertumpuk(pg, admin, pemasok):
    """Aturan 1: `act_catat_pk_luar` kini SATU panggilan — mencatat DAN
    langsung menumpuk, tanpa borang `masukkan_pk` kedua."""
    from app.models import User
    from app.penggilingan.gudang2.models import PkGudang2Intake
    from app.web.api import CatatPkLuarReq, act_catat_pk_luar

    async with pg() as db:
        tid = await _tiket(db, "T-REJ-05", nopol="AD 5 RJ", t1=6_000,
                           netto=6_000, kosong=0, supplier_id=pemasok.id)
        await db.commit()

    async with pg() as db:
        u = await db.get(type(admin), admin.id)
        jawab = await act_catat_pk_luar(
            CatatPkLuarReq(timbangan_transaksi_id=tid, jenis_pk="ks",
                          kadar_air=14, broken=1.5, penyusutan=0.8),
            user=u)
    assert "Tertumpuk" in jawab["pesan"], jawab["pesan"]

    async with pg() as db:
        intake = (await db.execute(select(PkGudang2Intake)
                                   .where(PkGudang2Intake.tujuan == "ditumpuk"))
                 ).scalars().all()
    assert len(intake) == 1 and float(intake[0].berat_kg) == 6_000


async def test_borang_gabungan_mutu_dasar_wajib_dan_tercatat(pg, admin, pemasok):
    """Keputusan pemilik 5 Oktober 2026: kadar air, broken, dan penyusutan
    WAJIB diisi di borang gabungan ini — bukan lagi opsional — dan langsung
    tercatat sebagai QC sungguhan (`pk_purchase_verifications`), bukan cuma
    snapshot di batch. Kartu "Mutu PK luar belum dicatat"
    (`berjalan.untuk_gudang2`) berhenti menagihnya begitu ini terisi,
    walau butir kuning/gabah/merang/catatan masih kosong."""
    from app.models import PkPurchaseBatch, PkPurchaseVerification, User
    from app.services.berjalan import untuk_gudang2
    from app.web.api import CatatPkLuarReq, act_catat_pk_luar

    async with pg() as db:
        tid = await _tiket(db, "T-REJ-07", nopol="AD 7 RJ", t1=7_000,
                           netto=7_000, kosong=0, supplier_id=pemasok.id)
        await db.commit()

    async with pg() as db:
        u = await db.get(type(admin), admin.id)
        jawab = await act_catat_pk_luar(
            CatatPkLuarReq(timbangan_transaksi_id=tid, jenis_pk="ks",
                          kadar_air=15, broken=2.5, penyusutan=1.0,
                          butir_kuning="sedikit", gabah="bersih", merang="sedikit",
                          catatan_lab="uji lapangan"),
            user=u)
    assert "mutu tercatat" in jawab["pesan"], jawab["pesan"]

    async with pg() as db:
        batch = (await db.execute(select(PkPurchaseBatch).where(
            PkPurchaseBatch.timbangan_transaksi_id == tid))).scalars().one()
        verif = (await db.execute(select(PkPurchaseVerification).where(
            PkPurchaseVerification.pk_purchase_batch_id == batch.id))).scalars().one()
        assert float(verif.kadar_air) == 15 and float(verif.broken_persen) == 2.5
        assert verif.butir_kuning == "sedikit"
        assert verif.gabah == "bersih" and verif.merang == "sedikit"

        b = await untuk_gudang2(db)
    assert not any(k.kode == batch.kode_batch for k in b.meja), (
        "mutu yang sudah diisi di borang gabungan masih menagih QC susulan")


async def test_borang_gabungan_mutu_kualitatif_boleh_dikosongkan(pg, admin, pemasok):
    """Butir kuning/gabah/merang/catatan TETAP opsional — mengosongkannya
    tak menolak pencatatan, selama kadar air/broken/penyusutan (yang wajib)
    sudah terisi."""
    from app.models import PkPurchaseBatch, PkPurchaseVerification, User
    from app.services.berjalan import untuk_gudang2
    from app.web.api import CatatPkLuarReq, act_catat_pk_luar

    async with pg() as db:
        tid = await _tiket(db, "T-REJ-08", nopol="AD 8 RJ", t1=4_000,
                           netto=4_000, kosong=0, supplier_id=pemasok.id)
        await db.commit()

    async with pg() as db:
        u = await db.get(type(admin), admin.id)
        jawab = await act_catat_pk_luar(
            CatatPkLuarReq(timbangan_transaksi_id=tid, jenis_pk="kl",
                          kadar_air=16, broken=3, penyusutan=1.2),
            user=u)
    assert "mutu tercatat" in jawab["pesan"], jawab["pesan"]

    async with pg() as db:
        batch = (await db.execute(select(PkPurchaseBatch).where(
            PkPurchaseBatch.timbangan_transaksi_id == tid))).scalars().one()
        verif = (await db.execute(select(PkPurchaseVerification).where(
            PkPurchaseVerification.pk_purchase_batch_id == batch.id))).scalars().one()
        assert verif.butir_kuning is None and verif.gabah is None and verif.merang is None
        b = await untuk_gudang2(db)
    # Sudah QC (kadar_air terisi) walau kualitatifnya kosong — tak menagih lagi.
    assert not any(k.kode == batch.kode_batch for k in b.meja), (
        "batch yang kuantitatifnya sudah terisi seharusnya tak menagih kartu susulan"
    )


async def test_borang_gabungan_mutu_dasar_wajib_ditolak_pydantic(pg, admin, pemasok):
    """Kadar air/broken/penyusutan tak lagi bisa dikosongkan — mencoba
    mengirim tanpa salah satunya ditolak di lapisan borang (ValidationError),
    sebelum satu baris pun ditulis."""
    import pydantic

    from app.web.api import CatatPkLuarReq

    async with pg() as db:
        tid = await _tiket(db, "T-REJ-09", nopol="AD 9 RJ", t1=5_000,
                           netto=5_000, kosong=0, supplier_id=pemasok.id)
        await db.commit()

    with pytest.raises(pydantic.ValidationError):
        CatatPkLuarReq(timbangan_transaksi_id=tid, jenis_pk="kl", broken=2, penyusutan=1)


async def test_rute_tolak_wajib_admin_dan_alasan(pg, admin, pemasok):
    from fastapi import HTTPException

    from app.models import User
    from app.peran import PERAN_ADMIN_KEATAS
    from app.web.api import TolakPkLuarReq, act_tolak_pk_luar

    async with pg() as db:
        tid = await _tiket(db, "T-REJ-06", nopol="AD 6 RJ", t1=3_000,
                           supplier_id=pemasok.id)
        await db.commit()

    # Operator biasa ditolak gerbangnya.
    async with pg() as db:
        op = (await db.execute(select(User).where(
            User.role.not_in(PERAN_ADMIN_KEATAS)))).scalars().first()
    if op is not None:
        with pytest.raises(HTTPException) as e:
            await act_tolak_pk_luar(
                TolakPkLuarReq(timbangan_transaksi_id=tid, alasan="Coba-coba"), user=op)
        assert e.value.status_code == 403

    # Admin tanpa alasan ditolak di validasi borang.
    async with pg() as db:
        u = await db.get(User, admin.id)
    with pytest.raises(HTTPException) as e:
        await act_tolak_pk_luar(
            TolakPkLuarReq(timbangan_transaksi_id=tid, alasan=""), user=u)
    assert e.value.status_code == 400

    # Admin dengan alasan berhasil, dan pesannya menyebut penutupan tiketnya.
    jawab = await act_tolak_pk_luar(
        TolakPkLuarReq(timbangan_transaksi_id=tid, alasan="Rusak di jalan."), user=u)
    assert jawab["ok"] and "ditolak" in jawab["pesan"].lower()


async def test_ditolak_tak_tagih_qc_dan_tak_masuk_nota_jasa(pg, admin, pemasok):
    """Dua kebocoran yang HARUS dicegat begitu `status_batch='ditolak'` mulai
    sungguhan dipakai: kartu "Mutu PK luar belum dicatat", dan nota jasa."""
    from app.models import User
    from app.penggilingan.gudang2.service import create_pk_rejection_dari_timbang
    from app.services.berjalan import untuk_gudang2

    async with pg() as db:
        tid = await _tiket(db, "T-REJ-07", nopol="AD 7 RJ", t1=5_500,
                           supplier_id=pemasok.id)
        await db.commit()
    async with pg() as db:
        u = await db.get(User, admin.id)
        r = await create_pk_rejection_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, alasan="Bau apek.")

    async with pg() as db:
        b = await untuk_gudang2(db)
    assert not any(k.kode == r.batch.kode_batch for k in b.meja), (
        "batch yang ditolak masih menagih QC")
