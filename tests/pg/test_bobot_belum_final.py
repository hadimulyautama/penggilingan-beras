"""Bobot yang belum ditimbang kedua kali — QA P6-01 s/d P6-04, 21 September 2026.

Laporan pemilik: Silo B berisi satu truk "0 kg" (belum ditimbang kedua) dan
satu truk 10.640 kg; operator mau mulai giling, ditolak terus dengan galat
Postgres mentah. Akar masalahnya satu pola di ~14 tempat:

    float(b.berat_total_kg or 0)

"Belum diketahui" diperlakukan sebagai NOL. Nol itu MENOLAK di tempat yang
menuntut > 0 (giling, PK luar masuk G2) dan MELOLOSKAN di tempat yang menuntut
≤ kapasitas (pengering). Basis datanya sendiri sudah membedakan keduanya:
CHECK (berat_kg IS NULL OR berat_kg > 0), migrasi 0040.

Keputusan pemilik 21 September: **Pilihan A** — perkiraan dari tara truk yang
sama (timbang pertama − berat kosong terakhir nomor polisi itu), ditandai
`sumber_berat='perkiraan'`, diganti netto sungguhan oleh poller; **B** sebagai
cadangan untuk truk yang belum pernah punya tara: bobotnya NULL, boleh masuk
silo/pengering/giling/G2, dan hanya rupiah yang menunggu bobot pasti.

Tiap uji di sini GAGAL pada kode sebelum perbaikan (dibuktikan 21 September
2026 sebelum satu baris pun disentuh), dan tiap butir punya skrip reproduksi
di QA/alat/p6/.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio


# Tiket dibuat lewat SQL mentah, bukan model timbangan — produksi memang tak
# memiliki tabel itu (lihat test_kontrak_timbangan). `berat_kosong_kg` ikut
# disebut karena dialah tara yang menjadi dasar perkiraan.
_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, timbang2_kg, timbang2_waktu,
         berat_kosong_kg, netto_timbangan_kg, berat_acuan_kg,
         status_tiket, status_transaksi)
    VALUES
        (:kode, :tanggal, 'MASUK', :jenis, 'DUA_KALI', :supplier_id, :pihak,
         :nopol, :t1, :waktu, :t2, :waktu2, :kosong, :netto, 0,
         :status_tiket, 'AKTIF')
    RETURNING id
""")


async def _tiket(db, kode, *, nopol, t1, netto=None, kosong=None, jenis="GABAH_KERING",
                 supplier_id=None, pihak="Pak Uji", hari_lalu=0):
    """Satu tiket MASUK. `netto` None = truk belum ditimbang kedua (TERBUKA)."""
    from app.database import now_local

    waktu = datetime.now(timezone.utc) - timedelta(days=hari_lalu)
    selesai = netto is not None
    return (await db.execute(_SQL_TIKET, {
        "kode": kode, "tanggal": (now_local() - timedelta(days=hari_lalu)).date(),
        "jenis": jenis, "supplier_id": supplier_id, "pihak": pihak, "nopol": nopol,
        "t1": t1, "waktu": waktu,
        "t2": (kosong if selesai else None), "waktu2": (waktu if selesai else None),
        "kosong": (kosong if selesai else None), "netto": netto,
        "status_tiket": "SELESAI" if selesai else "TERBUKA",
    })).scalar_one()


async def _timbang_kedua(db, tid, *, netto, kosong):
    await db.execute(text("""
        UPDATE timbangan_transaksi
           SET netto_timbangan_kg = :n, berat_kosong_kg = :k, timbang2_kg = :k,
               timbang2_waktu = now(), status_tiket = 'SELESAI'
         WHERE id = :i"""), {"n": netto, "k": kosong, "i": tid})


@pytest_asyncio.fixture
async def pabrik(pg, pemakai, pemasok):
    """Gudang, silo, satu pengering — lewat penyemai yang sama dengan produksi."""
    from app.models import Dryer, User, Warehouse
    from app.peran import PERAN_ADMIN_KEATAS
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g1 = (await db.execute(
            select(Warehouse).where(Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        # Penyemai sudah membuat satu pengering; kapasitasnya disamakan
        # dengan skenario QA (30 ton + toleransi). Dua pengering berarti
        # tiap aksi harus menyebut mesinnya — bukan yang sedang diuji.
        d = (await db.execute(select(Dryer).where(Dryer.warehouse_id == g1.id))).scalars().first()
        if d is None:
            d = Dryer(nama="Dryer 1", warehouse_id=g1.id, kapasitas_kg=30000, status="aktif")
            db.add(d)
        d.kapasitas_kg = 30000
        d.status = "aktif"
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g1.id
        # PK luar hanya boleh dicatat staf ke atas — satu orang lagi.
        adm = User(nama="Staf Uji", role=PERAN_ADMIN_KEATAS[-1], status="aktif",
                   default_warehouse_id=g1.id)
        db.add(adm)
        await db.commit()
        await db.refresh(adm)
    return {"g1": g1.id, "admin": adm.id}


async def _batch_gabah(pg, pemakai, tid, kondisi="kering"):
    from app.models import User
    from app.penggilingan.gudang1.services.purchase import create_purchase_batch_dari_timbang

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        r = await create_purchase_batch_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, kondisi_gabah=kondisi)
        return r.batch.kode_batch


async def _baca_batch(pg, kode):
    from app.models import PurchaseBatch

    async with pg() as db:
        return (await db.execute(
            select(PurchaseBatch).where(PurchaseBatch.kode_batch == kode))).scalars().one()


async def _poller(pg):
    """Persis urutan `run_sinkron_bobot_poller` — lewat satu pintu yang sama."""
    from app.penggilingan.gudang1.services.sinkron_bobot import satu_putaran

    return await satu_putaran()


# ─────────────────────── Pilihan A: perkiraan dari tara ───────────────────────

async def test_perkiraan_dari_tara_truk_yang_sama(pg, pemakai, pemasok, pabrik):
    """Tara satu truk hampir tak berubah dari muatan ke muatan (pemilik: "tara
    cenderung stabil"). Truk yang baru ditimbang bermuatan langsung punya
    bobot perkiraan = timbang pertama − berat kosong terakhirnya."""
    async with pg() as db:
        await _tiket(db, "T-LAMA", nopol="AD 1234 XY", t1=18000, netto=11500, kosong=6500,
                     supplier_id=pemasok.id, hari_lalu=3)
        tid = await _tiket(db, "T-BARU", nopol="ad1234xy", t1=17830, supplier_id=pemasok.id)
        await db.commit()

    kode = await _batch_gabah(pg, pemakai, tid)
    b = await _baca_batch(pg, kode)
    # Nomor polisi dinormalkan: huruf besar, tanpa spasi — "ad1234xy" adalah
    # truk yang sama dengan "AD 1234 XY".
    assert float(b.berat_total_kg) == 17830 - 6500
    assert b.sumber_berat == "perkiraan"
    assert float(b.berat_perkiraan_kg) == 17830 - 6500


async def test_tara_kedaluwarsa_tak_dipakai_menebak(pg, pemakai, pemasok, pabrik):
    """QA 24 September 2026 (c) butir 2c: tara dipakai APA ADANYA, tanpa batas
    umur sama sekali.

    "Tara cenderung stabil" berlaku dari muatan ke muatan — bukan sepanjang
    tahun. Terpal dipasang, bak diganti, alat naik, sopir kedua ikut. Yang
    lewat umur tak ditebak: bobotnya "menunggu timbang" (Pilihan B), sebab
    angka yang salah lebih mahal daripada angka yang belum ada.
    """
    from app.penggilingan.gudang1.services.bobot import UMUR_TARA_HARI

    async with pg() as db:
        await _tiket(db, "T-TUA", nopol="AD 9 TUA", t1=18000, netto=11500, kosong=6500,
                     supplier_id=pemasok.id, hari_lalu=UMUR_TARA_HARI + 5)
        tid = await _tiket(db, "T-KINI", nopol="AD 9 TUA", t1=17830, supplier_id=pemasok.id)
        await db.commit()

    b = await _baca_batch(pg, await _batch_gabah(pg, pemakai, tid))
    assert b.berat_total_kg is None and b.sumber_berat == "menunggu"

    # Poller pun tak menambalnya: syaratnya sama di kedua jalur, kalau tidak
    # yang menulis paling akhir yang menang.
    await _poller(pg)
    b = await _baca_batch(pg, b.kode_batch)
    assert b.berat_total_kg is None and b.sumber_berat == "menunggu"


async def test_tara_yang_tak_masuk_akal_tak_dipakai_menebak(pg, pemakai, pemasok, pabrik):
    """Skenario QA butir 2c, angkanya persis: tara LAMA 1.000 kg untuk truk yang
    sebenarnya 3.000 kg.

    Dulu keluar perkiraan 12.000 kg untuk muatan yang sebenarnya 10.000 —
    meleset 2 ton KE ATAS, dan kartunya tetap bisa digiling. Muatan 12 ton di
    atas truk bertara 1 ton adalah kendaraan yang tak ada; taranya milik
    kendaraan lain, atau salah ketik.
    """
    async with pg() as db:
        await _tiket(db, "T-PICKUP", nopol="B 1 SALAH", t1=4000, netto=3000, kosong=1000,
                     supplier_id=pemasok.id, hari_lalu=2)
        tid = await _tiket(db, "T-TRUK", nopol="B 1 SALAH", t1=13000, supplier_id=pemasok.id)
        await db.commit()

    b = await _baca_batch(pg, await _batch_gabah(pg, pemakai, tid))
    assert b.berat_total_kg is None, "perkiraan 12.000 kg dari tara 1.000 kg kembali"
    assert b.sumber_berat == "menunggu"
    await _poller(pg)
    assert (await _baca_batch(pg, b.kode_batch)).berat_total_kg is None

    # Dan begitu truknya benar-benar ditimbang kedua, angkanya masuk lewat
    # jalur yang sama seperti biasa — 10.000, bukan 12.000.
    async with pg() as db:
        await _timbang_kedua(db, tid, netto=10000, kosong=3000)
        await db.commit()
    await _poller(pg)
    b = await _baca_batch(pg, b.kode_batch)
    assert (float(b.berat_total_kg), b.sumber_berat) == (10000, "timbangan")


async def test_truk_tanpa_tara_tetap_tak_diketahui(pg, pemakai, pemasok, pabrik):
    """Truk baru tak punya tara historis → NULL, bukan nol dan bukan tebakan."""
    async with pg() as db:
        tid = await _tiket(db, "T-BARU2", nopol="B 9 XX", t1=17830, supplier_id=pemasok.id)
        await db.commit()
    kode = await _batch_gabah(pg, pemakai, tid)
    b = await _baca_batch(pg, kode)
    assert b.berat_total_kg is None
    assert b.sumber_berat == "menunggu"
    assert b.berat_perkiraan_kg is None


async def test_poller_mengganti_perkiraan_dan_menyimpan_selisihnya(pg, pemakai, pemasok, pabrik):
    """UJI ANGGAPAN PEMILIK, JANGAN HANYA MEMAKAINYA. Begitu timbang kedua
    datang, perkiraan diganti netto sungguhan lewat jalur yang sama dengan
    'menunggu' — dan selisihnya DISIMPAN, supaya truk yang taranya ternyata
    tidak stabil ketahuan dari data."""
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        await _tiket(db, "T-L1", nopol="AD 1 AA", t1=18000, netto=11500, kosong=6500,
                     supplier_id=pemasok.id, hari_lalu=2)
        t_meleset = await _tiket(db, "T-M", nopol="AD 1 AA", t1=17830, supplier_id=pemasok.id)
        await _tiket(db, "T-L2", nopol="AD 2 BB", t1=18000, netto=11500, kosong=6500,
                     supplier_id=pemasok.id, hari_lalu=2)
        t_tepat = await _tiket(db, "T-T", nopol="AD 2 BB", t1=17830, supplier_id=pemasok.id)
        await db.commit()
    k_meleset = await _batch_gabah(pg, pemakai, t_meleset)
    k_tepat = await _batch_gabah(pg, pemakai, t_tepat)
    assert (await _baca_batch(pg, k_meleset)).sumber_berat == "perkiraan"

    # Truk pertama: taranya bergeser (terpal, sopir kedua) → netto 10.900,
    # meleset 3,8 % dari perkiraan 11.330. Truk kedua tepat (11.300, 0,3 %).
    async with pg() as db:
        await _timbang_kedua(db, t_meleset, netto=10900, kosong=6930)
        await _timbang_kedua(db, t_tepat, netto=11300, kosong=6530)
        await db.commit()
    await _poller(pg)

    b1, b2 = await _baca_batch(pg, k_meleset), await _baca_batch(pg, k_tepat)
    assert (float(b1.berat_total_kg), b1.sumber_berat) == (10900, "timbangan")
    assert float(b1.berat_perkiraan_kg) == 11330, "perkiraannya tetap tersimpan"
    assert (float(b2.berat_total_kg), b2.sumber_berat) == (11300, "timbangan")

    async with pg() as db:
        d = await rekonsiliasi(db)
    meleset = d["perkiraan_meleset"]
    assert [x["kode_batch"] for x in meleset] == [k_meleset], meleset
    assert meleset[0]["nomor_polisi"] == "AD1AA"
    assert abs(float(meleset[0]["selisih_kg"]) - (10900 - 11330)) < 0.01
    assert not d["perkiraan"], "tak ada lagi yang berdiri di atas perkiraan"


# ──────────────── P6-01 · giling silo berisi truk belum ditimbang ────────────────

async def _ke_silo(pg, pemakai, kode, huruf="A", kode_lot=None):
    from app.models import User
    from app.penggilingan.gudang1.services.silo import masuk_silo

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await masuk_silo(db, user=u, nama_silo=huruf, kode_lot=kode_lot,
                         kode_batch=None if kode_lot else kode)


async def test_giling_silo_campuran_berjalan_tanpa_galat_basis_data(pg, pemakai, pemasok, pabrik):
    """Persis tangkapan layar: Catur (belum ditimbang, tanpa tara) + Widiyanto
    10.640 kg di satu silo. Dulu: CheckViolationError mentah. Sekarang: giling
    berjalan; bagian yang tak diketahui tercatat NULL, bukan 0."""
    from app.models import MillingProcess, MillingProcessSource, User
    from app.penggilingan.gudang1.services.milling import start_milling

    async with pg() as db:
        t_catur = await _tiket(db, "T-CATUR", nopol="AD 3 CC", t1=17830, supplier_id=pemasok.id)
        t_widi = await _tiket(db, "T-WIDI", nopol="AD 4 DD", t1=19000, netto=10640, kosong=8360,
                              supplier_id=pemasok.id)
        await db.commit()
    k_catur = await _batch_gabah(pg, pemakai, t_catur)
    k_widi = await _batch_gabah(pg, pemakai, t_widi)
    await _ke_silo(pg, pemakai, k_catur, "B")
    await _ke_silo(pg, pemakai, k_widi, "B")

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        r = await start_milling(db, user=u, nama_silo="B")
        kode_proses = r.proc.kode_proses
    async with pg() as db:
        proc = (await db.execute(
            select(MillingProcess).where(MillingProcess.kode_proses == kode_proses))).scalars().one()
        sumber = (await db.execute(
            select(MillingProcessSource).where(MillingProcessSource.milling_process_id == proc.id)
        )).scalars().all()
    assert proc.status == "proses"
    assert proc.bobot_masuk_final is False
    assert sorted((float(s.berat_kg) if s.berat_kg is not None else None) for s in sumber
                  if s.berat_kg is not None) == [10640]
    assert any(s.berat_kg is None for s in sumber), "yang tak diketahui NULL, bukan 0"
    assert float(proc.berat_gabah_masuk_kg) == 10640


async def test_giling_tertahan_sampai_ditimbang_kini_tidak_lagi(pg, pemakai, pemasok, pabrik):
    """Skenario E: satu truk sendirian di silo, belum ditimbang, tanpa tara."""
    from app.models import User
    from app.penggilingan.gudang1.services.milling import start_milling

    async with pg() as db:
        tid = await _tiket(db, "T-SUT", nopol="AD 5 EE", t1=18200, supplier_id=pemasok.id)
        await db.commit()
    kode = await _batch_gabah(pg, pemakai, tid)
    await _ke_silo(pg, pemakai, kode, "A")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        r = await start_milling(db, user=u, nama_silo="A")
    assert r.proc.berat_gabah_masuk_kg is None, "belum ada satu pun angka yang diketahui"
    assert r.proc.bobot_masuk_final is False


# ─────────────────── P6-02 · PK luar belum ditimbang masuk G2 ───────────────────

async def test_pk_luar_belum_ditimbang_bisa_masuk_tumpukan(pg, pemakai, pemasok, pabrik):
    """⚠ Dulu berjudul "...bisa masuk silo dan tumpukan" dan menguji
    keduanya — paritas yang justru DIHAPUS Aturan 1 (4 Oktober 2026): PK
    beli luar baru tak lagi boleh langsung ke silo, bobotnya diketahui atau
    tidak. Jalur silo diuji terpisah sebagai penolakan, di bawah; di sini
    cuma tumpukan, yang tetap menerima bobot belum pasti apa adanya."""
    from app.models import PkGudang2Intake, User
    from app.penggilingan.gudang2 import service as g2

    async with pg() as db:
        tid = await _tiket(db, "T-PK-tumpuk", nopol="AD 6 TU",
                           t1=9000, jenis="BERAS_PK", supplier_id=pemasok.id)
        await db.commit()
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        kode = (await g2.create_pk_purchase_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, jenis_pk="KS")).batch.kode_batch
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        r = await g2.masukkan_pk_luar(db, user=u, kode=kode, tujuan="ditumpuk")
    async with pg() as db:
        it = await db.get(PkGudang2Intake, r.intake.id)
        assert it.berat_kg is None
        assert it.bobot_final is False


async def test_pk_luar_belum_ditimbang_ditolak_langsung_ke_silo(pg, pemakai, pemasok, pabrik):
    """Aturan 1 tak punya pengecualian untuk bobot yang belum pasti — PK
    beli luar yang bobotnya belum diketahui JUGA harus ke tumpukan dulu,
    sama seperti yang bobotnya sudah pasti."""
    from app.models import User
    from app.penggilingan.gudang2 import service as g2

    async with pg() as db:
        tid = await _tiket(db, "T-PK-silo-a", nopol="AD 6 SA",
                           t1=9000, jenis="BERAS_PK", supplier_id=pemasok.id)
        await db.commit()
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        kode = (await g2.create_pk_purchase_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, jenis_pk="KS")).batch.kode_batch
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        with pytest.raises(g2.Gudang2Error) as e:
            await g2.masukkan_pk_luar(db, user=u, kode=kode, tujuan="silo_a")
    assert "tumpukan dulu" in str(e.value)


async def test_intake_g2_dilengkapi_poller_setelah_timbang_kedua(pg, pemakai, pemasok, pabrik):
    """⚠ Tujuannya "ditumpuk", bukan silo (Aturan 1, 4 Oktober 2026): PK baru
    tak lagi boleh langsung ke silo, dan `pindah_tumpukan_ke_silo` MENOLAK
    memindah tumpukan yang bobotnya belum diketahui — jadi "bobot belum
    pasti, lalu disosoh di silo" sudah tak tercapai lewat PK luar lagi.
    Mekanisme yang diuji di sini (poller melengkapi intake begitu tiketnya
    ditimbang kedua) tak peduli tujuannya silo atau tumpukan."""
    from app.models import PkGudang2Intake, User
    from app.penggilingan.gudang2 import service as g2

    async with pg() as db:
        tid = await _tiket(db, "T-PK-2", nopol="AD 7 GG", t1=9000, jenis="BERAS_PK",
                           supplier_id=pemasok.id)
        await db.commit()
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        kode = (await g2.create_pk_purchase_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, jenis_pk="KS")).batch.kode_batch
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        iid = (await g2.masukkan_pk_luar(db, user=u, kode=kode, tujuan="ditumpuk")).intake.id
    async with pg() as db:
        await _timbang_kedua(db, tid, netto=5200, kosong=3800)
        await db.commit()
    await _poller(pg)
    async with pg() as db:
        it = await db.get(PkGudang2Intake, iid)
        stok = await g2.hitung_stok_tumpukan(db)
    assert float(it.berat_kg) == 5200 and it.bobot_final is True
    assert stok == 5200


# ────────────── P6-03 · giling SELESAI sebelum truknya ditimbang ──────────────

async def _lot_kering(pg, pemakai, kodes: list[str]) -> str:
    from app.models import User
    from app.penggilingan.gudang1.services import drying as dr

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await dr.masuk_dryer(db, user=u, kode_batch_list=kodes)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        lot = (await dr.start_drying(db, user=u, target_kadar_air=14.0)).lot.kode_lot
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await dr.finish_drying(db, user=u, kode_lot=lot, kadar_air_akhir=14.0)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await dr.finish_cooling(db, user=u, kode_lot=lot)
    return lot


async def test_giling_selesai_duluan_ikut_dibetulkan(pg, pemakai, pemasok, pabrik):
    """Heru 7.190 kg + Joko MENUNGGU (nyatanya 2.000) dicampur di pengering,
    digiling, SELESAI dengan PK 5.700 — truk Joko baru ditimbang keesokan
    harinya. Dulu rendemen 79,3 % selamanya; seharusnya 62,0 %."""
    from app.models import MillingProcess, User
    from app.penggilingan.gudang1.services.milling import finish_milling, start_milling
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        t_heru = await _tiket(db, "T-HERU", nopol="AD 8 HH", t1=12000, netto=7190, kosong=4810,
                              jenis="GABAH_BASAH", supplier_id=pemasok.id)
        t_joko = await _tiket(db, "T-JOKO", nopol="AD 9 JJ", t1=5200, jenis="GABAH_BASAH",
                              supplier_id=pemasok.id)
        await db.commit()
    kh = await _batch_gabah(pg, pemakai, t_heru, "basah")
    kj = await _batch_gabah(pg, pemakai, t_joko, "basah")
    lot = await _lot_kering(pg, pemakai, [kh, kj])
    await _ke_silo(pg, pemakai, None, "A", kode_lot=lot)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        kode = (await start_milling(db, user=u, nama_silo="A")).proc.kode_proses
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await finish_milling(db, user=u, kode_proses=kode, berat_akhir=5700)

    async def baca():
        async with pg() as db:
            return (await db.execute(
                select(MillingProcess).where(MillingProcess.kode_proses == kode))).scalars().one()

    p = await baca()
    assert p.status == "selesai" and float(p.berat_gabah_masuk_kg) == 7190
    assert p.bobot_masuk_final is False
    async with pg() as db:
        d = await rekonsiliasi(db)
    assert [x["kode_proses"] for x in d["giling_belum_final"]] == [kode]

    # Hari kedua: truk Joko ditimbang. Poller lengkap berjalan seperti di server.
    async with pg() as db:
        await _timbang_kedua(db, t_joko, netto=2000, kosong=3200)
        await db.commit()
    await _poller(pg)
    p = await baca()
    assert float(p.berat_gabah_masuk_kg) == 7190 + 2000
    assert p.bobot_masuk_final is True
    async with pg() as db:
        d = await rekonsiliasi(db)
    assert not d["giling_belum_final"]


async def test_verifikasi_output_menunggu_bobot_final(pg, pemakai, pemasok, pabrik):
    """Rendemen final dan HPP berdiri di atas bahan masuk. Selama bahannya
    belum final, verifikasi output ditahan dengan alasan yang menyebut
    truknya — bukan diam-diam menghitung dari angka yang kurang."""
    from app.models import User
    from app.penggilingan.gudang1.services.milling import (
        MillingError, finish_milling, start_milling, verify_milling_output)

    async with pg() as db:
        tid = await _tiket(db, "T-VO", nopol="AD 10 KK", t1=18200, supplier_id=pemasok.id)
        await db.commit()
    kode = await _batch_gabah(pg, pemakai, tid)
    await _ke_silo(pg, pemakai, kode, "A")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        kp = (await start_milling(db, user=u, nama_silo="A")).proc.kode_proses
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await finish_milling(db, user=u, kode_proses=kp, berat_akhir=5000)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(MillingError, match="belum ditimbang"):
            await verify_milling_output(db, user=u, kode_proses=kp, berat_output=5000)


# ──────────────── P6-04 · pagar kapasitas pengering ────────────────

async def test_pagar_pengering_memakai_berat_kotor_untuk_truk_belum_ditimbang(
        pg, pemakai, pemasok, pabrik):
    """Truk yang belum ditimbang tak punya netto, tetapi punya berat KOTOR
    (timbang pertama) — dan kotor ≥ netto. Pagar memakai batas atas itu:
    yang muat dengan berat kotornya pasti muat dengan nettonya."""
    from app.models import User
    from app.penggilingan.gudang1.services import drying as dr

    async with pg() as db:
        t_isi = await _tiket(db, "T-ISI", nopol="AD 11 LL", t1=30000, netto=25500, kosong=4500,
                             jenis="GABAH_BASAH", supplier_id=pemasok.id)
        t_besar = await _tiket(db, "T-BESAR", nopol="AD 12 MM", t1=19000, jenis="GABAH_BASAH",
                               supplier_id=pemasok.id)
        t_kecil = await _tiket(db, "T-KECIL", nopol="AD 13 NN", t1=5000, jenis="GABAH_BASAH",
                               supplier_id=pemasok.id)
        await db.commit()
    k_isi = await _batch_gabah(pg, pemakai, t_isi, "basah")
    k_besar = await _batch_gabah(pg, pemakai, t_besar, "basah")
    k_kecil = await _batch_gabah(pg, pemakai, t_kecil, "basah")

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await dr.masuk_dryer(db, user=u, kode_batch_list=[k_isi])      # 25.500 dari 33.000
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(dr.DryingError, match="belum ditimbang"):
            await dr.masuk_dryer(db, user=u, kode_batch_list=[k_besar])  # kotor 19.000 > sisa 7.500
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await dr.masuk_dryer(db, user=u, kode_batch_list=[k_kecil])     # kotor 5.000 ≤ sisa
        load = await dr.dryer_load_kg(db)
    assert load == 25500, "yang tak diketahui tak dihitung sebagai angka apa pun"


# `test_verifikasi_harga_menunggu_bobot_pasti` DIBUANG 28 September 2026.
#
# Aturannya BENAR dan tidak dicabut — rupiah tak boleh berdiri di atas bobot
# perkiraan. Yang hilang subjeknya: `verify_gabah_price` dan `verify_pk_price`
# dihapus bersama seluruh harga (keputusan pemilik). Aturan itu kini milik
# keuangan, dan pagarnya harus berdiri di sana.
#
# Sisa berkas ini menjaga seluruh jalur BOBOT-nya, dan itu tidak berubah.


async def test_kartu_tak_menulis_nol_untuk_bobot_yang_belum_diketahui(pg, pemakai, pemasok, pabrik):
    from app.models import User
    from app.services import berjalan as svc

    async with pg() as db:
        await _tiket(db, "T-L11", nopol="AD 16 RR", t1=18000, netto=11500, kosong=6500,
                     supplier_id=pemasok.id, hari_lalu=1)
        t_perk = await _tiket(db, "T-PERK", nopol="AD 16 RR", t1=17830, supplier_id=pemasok.id)
        t_tunggu = await _tiket(db, "T-TUNGGU", nopol="AD 17 SS", t1=17830, supplier_id=pemasok.id)
        await db.commit()
    k_perk = await _batch_gabah(pg, pemakai, t_perk)
    k_tunggu = await _batch_gabah(pg, pemakai, t_tunggu)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        b = await svc.untuk(db, u)
    kartu = {r.kode: r for r in b.menunggu}
    assert "0 kg" not in kartu[k_tunggu].isi and "menunggu timbang" in kartu[k_tunggu].isi
    assert kartu[k_tunggu].utama is None
    assert "± 11.330 kg" in kartu[k_perk].isi
    assert kartu[k_perk].utama == ("± 11.330", "kg")
