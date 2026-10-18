"""Satu giling dari BEBERAPA silo — hasilnya SATU lot.

Keputusan pemilik 24 September 2026: menggiling dari beberapa silo sekaligus
"sering", dan "hasilnya 1 lot". Satu lot berarti satu rendemen dan satu HPP atas
seluruh bahan yang masuk — bukan dua lot yang harus dijumlah orang di kepalanya.

Yang diuji di sini BUKAN "apakah dua silo bisa dipilih" saja. Yang paling mahal
justru sisi yang tak kelihatan: silo yang IKUT tetapi tak ikut disembunyikan,
tak ikut dikosongkan, dan tak ikut dikembalikan saat pembatalan. Ketiganya
berakar pada satu kolom yang sama — `MillingProcess.silo_id` yang tunggal — dan
ketiganya melahirkan angka yang bohong dengan cara yang berbeda.
"""
from __future__ import annotations
from tests.pg.skenario_silo import pastikan_silo_kosong

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def silos(pg, pemakai, pemasok):
    """Tiga silo Gudang 1: A berisi 10.000 kg, B 6.000 kg, C KOSONG.

    C ada dengan sengaja: silo kosong harus DITOLAK, dan pagar yang diuji tanpa
    silo kosong di sekitarnya membuktikan nol.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import PurchaseBatch, Silo, SiloStorage, User, Warehouse

    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
            db.add(g1)
            await db.flush()
        huruf_silo = {}
        for huruf in ("A", "B", "C"):
            s = (await db.execute(select(Silo).where(
                Silo.nama_silo == f"Silo {huruf}",
                Silo.warehouse_id == g1.id))).scalars().first()
            if s is None:
                s = Silo(nama_silo=f"Silo {huruf}", warehouse_id=g1.id, status="kosong")
                db.add(s)
                await db.flush()
            huruf_silo[huruf] = s

        u = await db.get(User, pemakai.id)
        isi = {}
        for huruf, kg in (("A", 10_000), ("B", 6_000)):
            b = PurchaseBatch(
                kode_batch=f"GB-MS-{huruf}", supplier_id=pemasok.id,
                berat_total_kg=kg, kondisi_gabah="kering",
                tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                input_by=u.id, flag_unverified=False, sumber_berat="timbangan",
                status_batch="di_silo")
            db.add(b)
            await db.flush()
            st = SiloStorage(silo_id=huruf_silo[huruf].id, purchase_batch_id=b.id,
                             tipe_masuk="langsung_kering", tanggal_masuk=now_local(),
                             input_by=u.id, status="terisi")
            db.add(st)
            huruf_silo[huruf].status = "terisi"
            await db.flush()
            isi[huruf] = {"batch": b.id, "storage": st.id, "kg": kg}
        await db.commit()
        return {"silo": {h: s.id for h, s in huruf_silo.items()}, "isi": isi,
                "user": u.id}


async def _mulai(pg, silos, huruf, **kw):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import start_milling

    async with pg() as db:
        u = await db.get(User, silos["user"])
        r = await start_milling(db, user=u, nama_silo=huruf, **kw)
        return r


# ─────────────────── 1 · Mulai dari beberapa silo ───────────────────

async def test_dua_silo_jadi_satu_lot(pg, silos):
    """Satu proses, dua baris sumber, dan bahannya DIJUMLAH."""
    from sqlalchemy import select

    from app.models import MillingProcess, MillingProcessSource

    r = await _mulai(pg, silos, ["A", "B"])
    assert r.nama_silo == "A + B", "kalimatnya hanya menyebut satu silo"
    assert float(r.berat_masuk) == 16_000

    async with pg() as db:
        proses = (await db.execute(select(MillingProcess))).scalars().all()
        assert len(proses) == 1, "dua silo melahirkan dua lot"
        sumber = (await db.execute(select(MillingProcessSource).where(
            MillingProcessSource.milling_process_id == proses[0].id))).scalars().all()
        assert len(sumber) == 2
        assert float(proses[0].berat_gabah_masuk_kg) == 16_000


async def test_semua_silo_keluar_dari_antrean_dan_dari_borang(pg, silos):
    """⚠ INILAH yang paling berbahaya.

    Kalau hanya silo yang tercatat di `silo_id` yang disembunyikan, silo KEDUA
    tetap berkartu "siap digiling" — lengkap dengan tombolnya — padahal gabahnya
    sudah di dalam mesin. Yang menekannya memulai giling kedua atas gabah yang
    sama, dan dua rendemen lahir dari satu muatan.
    """
    from app.models import User
    from app.services.berjalan import untuk_gudang1
    from app.web.api import silo_siap_giling

    await _mulai(pg, silos, ["A", "B"])
    async with pg() as db:
        b = await untuk_gudang1(db)
        u = await db.get(User, silos["user"])
        u.role = "superadmin"
        await db.commit()
        await db.refresh(u)

    kartu_silo = [x for x in b.transit if x.aksi == "mulai_giling"]
    assert kartu_silo == [], f"silo yang digiling masih bertombol: {kartu_silo}"
    # Silo C kosong tak berkartu juga — tapi bukan karena sedang digiling.
    assert not any("Silo A" in (x.kode or "") or "Silo B" in (x.kode or "")
                   for x in b.transit)
    daftar = [x["value"] for x in await silo_siap_giling(user=u)]
    assert daftar == [], f"borang masih menawarkan silo yang di mesin: {daftar}"


async def test_tiga_silo(pg, silos):
    """Dua bukan angka istimewa. Silo Gudang 1 bisa bertambah lewat Pengaturan,
    jadi yang diuji bukan "dua" melainkan "beberapa"."""
    from app.database import now_local
    from app.models import PurchaseBatch, SiloStorage, User

    async with pg() as db:
        u = await db.get(User, silos["user"])
        b = PurchaseBatch(kode_batch="GB-MS-C", supplier_id=None,
                          berat_total_kg=2_000, kondisi_gabah="kering",
                          tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                          input_by=u.id, flag_unverified=False,
                          sumber_berat="timbangan", status_batch="di_silo")
        # `supplier_id` wajib isi — dipinjam dari salah satu batch yang ada.
        from sqlalchemy import select
        b.supplier_id = (await db.execute(select(PurchaseBatch.supplier_id).limit(1))).scalar()
        db.add(b)
        await db.flush()
        db.add(SiloStorage(silo_id=silos["silo"]["C"], purchase_batch_id=b.id,
                           tipe_masuk="langsung_kering", tanggal_masuk=now_local(),
                           input_by=u.id, status="terisi"))
        await db.commit()

    r = await _mulai(pg, silos, ["A", "B", "C"])
    assert r.nama_silo == "A + B + C"
    assert float(r.berat_masuk) == 18_000


async def test_silo_kosong_ditolak_dan_tak_melahirkan_lot_separuh(pg, silos):
    """Lot separuh lebih buruk daripada lot yang gagal dimulai: ia berdiri di
    layar sebagai giling yang berjalan, rendemennya dihitung atas bahan yang tak
    lengkap, dan tak ada kalimat yang menyebut silo mana yang tertinggal."""
    from sqlalchemy import select

    from app.models import MillingProcess
    from app.penggilingan.gudang1.services.milling import MillingError

    with pytest.raises(MillingError) as e:
        await _mulai(pg, silos, ["A", "C"])
    assert "Silo C kosong" in str(e.value)

    async with pg() as db:
        assert (await db.execute(select(MillingProcess))).scalars().all() == [], \
            "lot separuh tetap lahir meski satu silonya ditolak"
        # Dan silo A tetap boleh digiling sesudahnya — penolakan tak meninggalkan
        # klaim yang menggantung.
    r = await _mulai(pg, silos, ["A"])
    assert float(r.berat_masuk) == 10_000


# ─────────────────── 5 & 6 · Dua giling atas silo yang sama ───────────────────

async def test_silo_yang_jadi_sumber_proses_lain_ditolak(pg, silos):
    """Termasuk bila silo itu cuma SALAH SATU sumber proses yang berjalan —
    di situlah pagar lama (indeks unik atas `silo_id`) tidak berlaku."""
    from app.penggilingan.gudang1.services.milling import MillingError

    await _mulai(pg, silos, ["A", "B"])
    for huruf in (["B"], ["A"], ["B", "A"]):
        with pytest.raises(MillingError) as e:
            await _mulai(pg, silos, huruf)
        assert "sedang digiling" in str(e.value)


async def test_silo_berbeda_tetap_boleh(pg, silos):
    """Pagar yang terlalu lebar sama merusaknya: dua mesin giling memang boleh
    berjalan bersamaan atas silo yang berbeda."""
    await _mulai(pg, silos, ["A"])
    r = await _mulai(pg, silos, ["B"])
    assert float(r.berat_masuk) == 6_000


async def test_dua_permintaan_bersamaan_satu_menang(pg, silos):
    """Pagarnya di BASIS DATA, bukan di pemeriksaan di depan.

    Dua operator yang menekan pada detik yang sama sama-sama lolos pemeriksaan
    "sedang digiling?" — keduanya membaca "belum", lalu keduanya menulis. Yang
    memutuskan `UPDATE … WHERE milling_process_id IS NULL`: Postgres mengunci
    barisnya lalu menguji ulang syaratnya sesudah kunci didapat.

    Dua SESI sungguhan, bukan dua panggilan berurutan: yang berurutan diuji di
    atas, dan ia tak pernah menyentuh perlombaannya.
    """
    import asyncio

    from app.models import User
    from app.penggilingan.gudang1.services.milling import MillingError, start_milling

    async def coba():
        async with pg() as db:
            u = await db.get(User, silos["user"])
            try:
                r = await start_milling(db, user=u, nama_silo=["A"])
                return r.proc.kode_proses
            except MillingError as e:
                return f"tolak: {e}"

    hasil = await asyncio.gather(coba(), coba())
    menang = [x for x in hasil if not x.startswith("tolak")]
    tolak = [x for x in hasil if x.startswith("tolak")]
    assert len(menang) == 1 and len(tolak) == 1, hasil
    # Kalimatnya harus bisa dibaca operator, bukan teks Postgres.
    assert "Silo A" in tolak[0] or "silonya baru saja dipakai" in tolak[0]
    assert "IntegrityError" not in tolak[0] and "psycopg" not in tolak[0].lower()


# ─────────────────── 2, 3, 4 · Satu lot, satu rendemen ───────────────────

async def test_satu_rendemen_atas_bahan_seluruh_silo(pg, silos):
    """Penyebutnya jumlah bahan SELURUH silo. Kalau ia tinggal di silo pertama,
    rendemen 6.000/16.000 = 37,5% terbaca 60% — dan 60% dari gabah kering adalah
    angka yang tampak wajar, jadi tak ada yang akan mencurigainya."""
    from app.models import User
    from app.penggilingan.gudang1.services.milling import finish_milling

    from app.penggilingan.gudang1.services.milling import hitung_rendemen

    r = await _mulai(pg, silos, ["A", "B"])
    async with pg() as db:
        u = await db.get(User, silos["user"])
        await pastikan_silo_kosong(db, user=u, kode_proses=r.proc.kode_proses)
        s = await finish_milling(db, user=u, kode_proses=r.proc.kode_proses,
                                 berat_akhir=6_000)
    # Penyebutnya dibaca dari prosesnya sendiri — di situlah "satu lot, satu
    # rendemen" hidup atau mati.
    assert float(s.proc.berat_gabah_masuk_kg) == 16_000
    assert hitung_rendemen(s.produced, s.proc.berat_gabah_masuk_kg) == \
        pytest.approx(37.5, abs=0.05)


async def test_batch_asal_memuat_isi_seluruh_silo(pg, silos):
    """Inilah yang menjawab "beras ini dari gabah siapa". Sumber yang hilang
    membuat pertanyaan itu tak terjawab justru saat ada keluhan mutu."""
    from app.services.stok import pk_gudang1
    from app.models import User
    from app.penggilingan.gudang1.services.milling import finish_milling

    r = await _mulai(pg, silos, ["A", "B"])
    async with pg() as db:
        u = await db.get(User, silos["user"])
        await pastikan_silo_kosong(db, user=u, kode_proses=r.proc.kode_proses)
        await finish_milling(db, user=u, kode_proses=r.proc.kode_proses,
                                 berat_akhir=6_000)
    async with pg() as db:
        lot = next(l for l in await pk_gudang1(db) if l.kode == r.proc.kode_proses)
    # Bentuknya tupel (pemasok · kode batch, berat, kapan) — yang dicari
    # kodenya, di mana pun ia duduk di dalam barisnya.
    teks = " | ".join(" ".join(str(y) for y in x) for x in lot.bahan)
    assert "GB-MS-A" in teks and "GB-MS-B" in teks, f"asalnya tak lengkap: {lot.bahan}"


async def test_selesai_setelah_operator_memastikan_seluruh_silo_kosong(pg, silos):
    """Silo kedua yang tetap "terisi" menunjukkan gabah yang tidak ada, dan orang
    mencari-carinya."""
    from sqlalchemy import select

    from app.models import MillingProcessSource, Silo, SiloStorage, User
    from app.penggilingan.gudang1.services.milling import finish_milling

    r = await _mulai(pg, silos, ["A", "B"])
    async with pg() as db:
        u = await db.get(User, silos["user"])
        await pastikan_silo_kosong(db, user=u, kode_proses=r.proc.kode_proses)
        await finish_milling(db, user=u, kode_proses=r.proc.kode_proses,
                                 berat_akhir=6_000)

    async with pg() as db:
        for huruf in ("A", "B"):
            silo = await db.get(Silo, silos["silo"][huruf])
            assert silo.status == "kosong", f"Silo {huruf} masih terisi"
        baris = (await db.execute(select(SiloStorage).where(
            SiloStorage.id.in_([silos["isi"]["A"]["storage"],
                                silos["isi"]["B"]["storage"]])))).scalars().all()
        assert all(b.status == "kosong" for b in baris), "baris silo tak ikut kosong"
        # Klaimnya ikut dilepas — kolom yang artinya tergantung kolom lain
        # adalah kolom yang dibaca salah suatu hari.
        assert all(b.milling_process_id is None for b in baris)
        # Dan kedua batch-nya "digiling", bukan satu (QA P-K-18).
        from app.models import PurchaseBatch
        st = (await db.execute(select(PurchaseBatch.status_batch).where(
            PurchaseBatch.kode_batch.in_(("GB-MS-A", "GB-MS-B"))))).scalars().all()
        assert set(st) == {"digiling"}, st
        assert (await db.execute(select(MillingProcessSource))).scalars().all()


# ─────────────────── 7 · Undo ───────────────────

async def test_undo_selesai_tidak_membatalkan_pemeriksaan_silo(pg, silos):
    """Pembatalan yang mengembalikan separuh keadaan lebih buruk daripada
    pembatalan yang menolak: tak ada satu pun layar yang menyebut separuh mana
    yang tertinggal."""
    from sqlalchemy import select

    from app.models import PurchaseBatch, Silo, SiloStorage, User
    from app.penggilingan.gudang1.services.milling import finish_milling
    from app.services import undo

    r = await _mulai(pg, silos, ["A", "B"])
    async with pg() as db:
        u = await db.get(User, silos["user"])
        await pastikan_silo_kosong(db, user=u, kode_proses=r.proc.kode_proses)
        await finish_milling(db, user=u, kode_proses=r.proc.kode_proses,
                                 berat_akhir=6_000)
    async with pg() as db:
        u = await db.get(User, silos["user"])
        c = await undo.cakupan(db, scope="saya", nama=None, self_id=u.id)
        pesan = await undo.undo_last(db, actor=u, cakupan=c)
        await db.commit()
    assert "selesai giling" in pesan, pesan

    async with pg() as db:
        for huruf in ("A", "B"):
            silo = await db.get(Silo, silos["silo"][huruf])
            assert silo.status == "kosong", f"Silo {huruf} tidak boleh diisi ulang secara semu"
        baris = (await db.execute(select(SiloStorage).where(
            SiloStorage.id.in_([silos["isi"]["A"]["storage"],
                                silos["isi"]["B"]["storage"]])))).scalars().all()
        assert all(b.status == "kosong" for b in baris)
        # Prosesnya kembali 'proses', jadi klaimnya kembali terpasang — tanpa
        # itu silo yang sama bisa direbut proses kedua.
        assert all(b.milling_process_id is None for b in baris)
        st = (await db.execute(select(PurchaseBatch.status_batch).where(
            PurchaseBatch.kode_batch.in_(("GB-MS-A", "GB-MS-B"))))).scalars().all()
        assert set(st) == {"digiling"}, f"status batch tak ikut kembali: {st}"


async def test_undo_mulai_melepas_seluruh_klaim(pg, silos):
    """Klaim yang tertinggal membuat silo tak bisa digiling lagi oleh siapa pun,
    dan tak ada satu pun kalimat di layar yang menyebutkan sebabnya."""
    from sqlalchemy import select

    from app.models import SiloStorage, User
    from app.services import undo

    await _mulai(pg, silos, ["A", "B"])
    async with pg() as db:
        u = await db.get(User, silos["user"])
        c = await undo.cakupan(db, scope="saya", nama=None, self_id=u.id)
        pesan = await undo.undo_last(db, actor=u, cakupan=c)
        await db.commit()
    assert "mulai giling" in pesan, pesan

    async with pg() as db:
        baris = (await db.execute(select(SiloStorage))).scalars().all()
        assert all(b.milling_process_id is None for b in baris)
    # Buktinya: bisa dimulai lagi.
    r = await _mulai(pg, silos, ["A", "B"])
    assert float(r.berat_masuk) == 16_000


# ─────────────────── 8 · Lot LAMA tetap terbaca ───────────────────

async def test_lot_satu_silo_tak_berubah_sama_sekali(pg, silos):
    """Proses satu-silo punya satu baris sumber, jadi himpunannya berisi satu —
    dan hasilnya harus sama dengan sebelum perubahan ini: bahan, rendemen, silo
    yang dikosongkan, dan kalimatnya."""
    from app.models import Silo, User
    from app.penggilingan.gudang1.services.milling import finish_milling

    from app.penggilingan.gudang1.services.milling import hitung_rendemen

    r = await _mulai(pg, silos, "A")          # bentuk TUNGGAL, seperti dulu
    assert r.nama_silo == "A" and float(r.berat_masuk) == 10_000
    async with pg() as db:
        u = await db.get(User, silos["user"])
        await pastikan_silo_kosong(db, user=u, kode_proses=r.proc.kode_proses)
        s = await finish_milling(db, user=u, kode_proses=r.proc.kode_proses,
                                 berat_akhir=6_000)
    assert hitung_rendemen(s.produced, s.proc.berat_gabah_masuk_kg) == \
        pytest.approx(60.0, abs=0.05)
    assert s.nama_silo is None
    async with pg() as db:
        assert (await db.get(Silo, silos["silo"]["A"])).status == "kosong"
        assert (await db.get(Silo, silos["silo"]["B"])).status == "terisi"


async def test_proses_lama_tanpa_baris_sumber_tetap_terbaca(pg, silos):
    """Proses yang lahir SEBELUM `milling_process_sources` ada tak punya satu
    baris sumber pun. Kaki kedua (`silo_id`) yang menjawab untuknya — tanpa itu,
    giling lama yang sedang berputar terbaca "tidak ada" dan silonya ditawarkan
    lagi kepada operator yang sedang menunggui mesinnya sendiri.
    """
    from sqlalchemy import delete, select

    from app.database import now_local
    from app.models import MillingProcess, MillingProcessSource, User
    from app.penggilingan.gudang1.services.silo import giling_berjalan_untuk_silo

    async with pg() as db:
        u = await db.get(User, silos["user"])
        p = MillingProcess(kode_proses="LOT-LAMA-01", status="proses",
                           silo_id=silos["silo"]["A"],
                           silo_storage_id=silos["isi"]["A"]["storage"],
                           berat_gabah_masuk_kg=10_000, waktu_mulai=now_local(),
                           created_by=u.id)
        db.add(p)
        await db.commit()
        await db.execute(delete(MillingProcessSource).where(
            MillingProcessSource.milling_process_id == p.id))
        await db.commit()

    async with pg() as db:
        jalan = await giling_berjalan_untuk_silo(db, silos["silo"]["A"])
        assert jalan is not None and jalan.kode_proses == "LOT-LAMA-01"
        assert await giling_berjalan_untuk_silo(db, silos["silo"]["B"]) is None


# ─────────────── Gabah yang datang ke silo KEDUA saat giling jalan ───────────────

async def test_gabah_ke_silo_kedua_ikut_jadi_sumber(pg, silos):
    """Gabah yang masuk ke silo kedua sebuah giling dulu tak ikut didaftar: ia
    tergiling, tetapi `berat_gabah_masuk_kg` tinggal di angka lama — dan
    rendemennya melambung tanpa ada yang tahu sebabnya."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import MillingProcess, MillingProcessSource, PurchaseBatch, User
    from app.penggilingan.gudang1.services.silo import masuk_silo

    r = await _mulai(pg, silos, ["A", "B"])
    async with pg() as db:
        u = await db.get(User, silos["user"])
        sup = (await db.execute(select(PurchaseBatch.supplier_id).limit(1))).scalar()
        b = PurchaseBatch(kode_batch="GB-MS-TAMBAH", supplier_id=sup,
                          berat_total_kg=1_500, kondisi_gabah="kering",
                          tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                          input_by=u.id, flag_unverified=False,
                          sumber_berat="timbangan", status_batch="diterima")
        db.add(b)
        await db.commit()
        # Ke silo B — silo KEDUA proses itu, yang tak tercatat di `silo_id`.
        hasil = await masuk_silo(db, user=u, nama_silo="B", kode_lot=None,
                                 kode_batch="GB-MS-TAMBAH")

    assert hasil.giling_berjalan == r.proc.kode_proses, \
        "gabah ke silo kedua tak ikut proses yang berjalan"
    async with pg() as db:
        p = (await db.execute(select(MillingProcess).where(
            MillingProcess.kode_proses == r.proc.kode_proses))).scalars().one()
        assert float(p.berat_gabah_masuk_kg) == 17_500
        n = (await db.execute(select(MillingProcessSource).where(
            MillingProcessSource.milling_process_id == p.id))).scalars().all()
        assert len(n) == 3


async def test_kartu_giling_menyebut_silo_hasil_dan_rendemennya(pg, silos):
    """Laporan operator Gudang 1, 28 September 2026: "hasil giling ditulis
    lebih dari jumlah gabah bisa tersimpan, tetapi angka yg tertera sama
    seperti berat gabah."

    Diperiksa QA: angkanya TIDAK dipotong — yang keliru kartunya. Angka
    besarnya BAHAN MASUK, dan hasilnya tak pernah muncul sama sekali. Operator
    menekan "Perbarui hasil giling", kembali ke kartunya, melihat angka gabah
    — dan menyimpulkan hasilnya diganti jadi berat gabah.

    Ini KETIGA KALINYA kartu ini kurang informasi; silonya juga tak pernah
    disebut (temuan QA 27 September). Bentuknya kini sama dengan kartu
    penyosohan: Silo · Bahan · Hasil + rendemen. Dua gudang yang mengerjakan
    hal serupa tak boleh berkartu beda bentuk — orangnya berpindah antar
    gudang.
    """
    from app.models import User
    from app.penggilingan.gudang1.services.milling import log_progress
    from app.services.berjalan import untuk_gudang1

    r = await _mulai(pg, silos, ["A", "B"])
    async with pg() as db:
        u = await db.get(User, silos["user"])
        await log_progress(db, user=u, kode_proses=r.proc.kode_proses,
                           berat_kumulatif=6_000)

    async with pg() as db:
        b = await untuk_gudang1(db)
    k = next(x for x in b.berjalan if x.kode == r.proc.kode_proses)
    fakta = {nama: nilai for nama, nilai in (k.fakta or [])}

    assert "Silo" in fakta, f"kartu giling tak menyebut silonya: {fakta}"
    assert "A" in fakta["Silo"] and "B" in fakta["Silo"], fakta["Silo"]
    assert "Hasil" in fakta, f"kartu giling tak menyebut hasilnya: {fakta}"
    assert "6.000" in fakta["Hasil"], fakta["Hasil"]
    assert "rendemen" in fakta["Hasil"], "hasil tanpa rendemennya"
    # Dan baris ringkasnya — yang dibaca di Beranda — ikut menyebutnya.
    assert "hasil" in (k.ringkas or "").lower(), k.ringkas


async def test_kartu_giling_tanpa_hasil_tak_mengarang_rendemen(pg, silos):
    """Sebelum satu angka pun dicatat, kartunya diam soal hasil — bukan
    menyebut nol. Nol yang dicetak sebagai fakta terbaca seperti hasil yang
    sudah diukur, dan rendemen 0% akan dicari sebabnya di mesin."""
    from app.services.berjalan import untuk_gudang1

    r = await _mulai(pg, silos, ["A"])
    async with pg() as db:
        b = await untuk_gudang1(db)
    k = next(x for x in b.berjalan if x.kode == r.proc.kode_proses)
    fakta = {nama: nilai for nama, nilai in (k.fakta or [])}
    assert "Hasil" not in fakta, fakta
    assert "Silo" in fakta, "silonya tetap disebut sejak awal"
