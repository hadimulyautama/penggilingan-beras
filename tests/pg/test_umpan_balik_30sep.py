"""Umpan balik lapangan 30 September 2026 — tumpukan & rendemen.

Dua laporan yang sebabnya sama sekali berbeda, dan keduanya hanya terlihat
oleh orang yang memakai aplikasinya setiap hari:

  · "1 lot pk dari luar yg ditumpuk, lalu dimasukkan ke silo lebih dari 1 kali,
    pada tumpukan yg dimasukkan terakhir kali harus bersisa minimal 1 kg" —
    bukan cacat aritmetika melainkan LABEL yang membulatkan ke atas sementara
    pagarnya tidak. Operator mengetik angka yang dibacanya di layar, dan
    layarnya menawarkan satu kilogram yang tak ada;

  · "hasil rendemen gudang 2 hanya muncul pada KABAR admin saja" — benar, dan
    kabar itu memang untuk Admin (isinya menagih verifikasi). Yang salah bukan
    tujuan kabarnya melainkan bahwa orang yang menjalankan mesinnya tak pernah
    tahu hasil kerjanya.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def g2(pg):
    """Gudang 2 bersilo, satu operator, satu admin — dan satu tumpukan PK
    seberat 2.999,6 kg: angka yang dibulatkan label jadi "3.000 kg"."""
    from app.database import now_local
    from app.models import Silo, Supplier, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar
    from app.peran import PERAN_ADMIN_KEATAS
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        gd = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add(gd)
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=gd.id),
                    Silo(nama_silo="Silo B", warehouse_id=gd.id)])
        op = User(nama="Op Polesan", role="operator", status="aktif",
                  default_warehouse_id=gd.id)
        adm = User(nama="Admin Uji", role=PERAN_ADMIN_KEATAS[-1], status="aktif")
        s = Supplier(nama_supplier="UD Sumber")
        db.add_all([op, adm, s])
        await db.flush()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-TMP-01", supplier_id=s.id, berat_total_kg=2_999.6,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=adm.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
        a = await db.get(User, adm.id)
        r = await masukkan_pk_luar(db, user=a, kode="PKB-TMP-01",
                                   tujuan="ditumpuk")
        return {"op": op.id, "adm": adm.id, "intake": r.intake.id, "gd": gd.id}


async def _sisa(pg, intake_id) -> float:
    from app.penggilingan.gudang2.service import _sisa_tumpukan_intake
    async with pg() as db:
        return float(await _sisa_tumpukan_intake(db, intake_id) or 0)


# ───────────────────────── Tumpukan → silo ─────────────────────────

async def test_label_tumpukan_tak_membulatkan_ke_atas(pg, g2):
    """Sebab sesungguhnya laporan "harus bersisa 1 kg".

    `_kg` membulatkan setengah KE ATAS, jadi sisa 2.999,6 kg terbaca
    "3.000 kg". Operator mengetik angka yang ditawarkan layar kepadanya, dan
    pagarnya menolaknya. Ia hanya menggigit di pemindahan TERAKHIR — di situlah
    orang mengetik angka dari layar, bukan angka kerja yang bulat.
    """
    from app.services.berjalan import _kartu_tumpukan_g2

    async with pg() as db:
        kartu = await _kartu_tumpukan_g2(db)
    assert kartu, "tumpukannya tak berkartu"
    angka = kartu[0].utama[0]
    assert "3.000" not in angka, (
        f"label masih membulatkan ke atas: {angka} — layar menawarkan satu "
        "kilogram yang tak ada, lalu pagarnya menolaknya")
    assert "2.999" in angka, angka


async def test_angka_dari_layar_diterima_dan_tumpukan_habis(pg, g2):
    """Toleransi sekata: yang diketik manusia dibandingkan dengan angka
    timbangan, dan menuntut kesamaan sampai gram tidak masuk akal.

    Yang DIPINDAHKAN tetap `min(berat, sisa)` — toleransi membuat angkanya
    diterima, bukan membuat tumpukan berutang.
    """
    from app.models import User
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo

    async with pg() as db:
        r = await pindah_tumpukan_ke_silo(
            db, user=await db.get(User, g2["op"]), intake_id=g2["intake"],
            nama_silo="A", berat=3_000)          # angka bulat dari layar
    assert abs(r.berat_kg - 2_999.6) < 0.01, r.berat_kg
    assert await _sisa(pg, g2["intake"]) <= 0.001, \
        "tumpukan masih bersisa — persis keluhan operator"


async def test_kotak_berat_kosong_memindahkan_seluruh_sisanya(pg, g2):
    """Jalan yang tak perlu mengetik sama sekali — itu yang menghapus seluruh
    kelas masalahnya, bukan menggesernya satu desimal."""
    from app.models import User
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo

    async with pg() as db:
        r = await pindah_tumpukan_ke_silo(
            db, user=await db.get(User, g2["op"]), intake_id=g2["intake"],
            nama_silo="A", berat=None)
    assert abs(r.berat_kg - 2_999.6) < 0.01, r.berat_kg
    assert await _sisa(pg, g2["intake"]) <= 0.001


async def test_borang_menawarkan_kotak_berat_yang_boleh_kosong(pg, g2):
    """Kemampuannya sudah lama ada di layanan ("`berat` None = pindah semua");
    yang tak pernah ada cuma TAWARANNYA di layar. Kemampuan yang tak
    ditawarkan sama saja dengan kemampuan yang tak ada.

    Dibaca dari SUMBER spesifikasinya: medan yang `wajib` akan dihadang
    peramban sebelum satu permintaan pun dikirim, jadi uji lewat HTTP tak
    pernah menyentuh keadaan ini.
    """
    import inspect

    from app.web import api

    sumber = inspect.getsource(api)
    i = sumber.index('"id": "pindah_tumpukan_silo"')
    potong = sumber[i:i + 2200]
    assert '"name": "berat_kg"' in potong, "medan beratnya hilang dari borang"
    kotak = potong[potong.index('"name": "berat_kg"'):]
    assert '"wajib": True' not in kotak[:300], \
        "kotak beratnya masih wajib — 'seluruh sisanya' tak bisa dipilih"
    assert "KOSONGKAN" in potong, \
        "tawarannya tak tertulis di mana pun yang dibaca operator"


async def test_berat_jauh_di_atas_sisa_tetap_ditolak(pg, g2):
    """Toleransi SATU kilogram, bukan pintu terbuka.

    Yang dilonggarkan cuma selisih pembulatan; salah ketik yang sungguhan —
    3.000 jadi 9.999 — tetap harus ditolak, dan ditolak sambil menyebut kedua
    angkanya supaya yang mengetik tahu mana yang benar.
    """
    from app.models import User
    from app.penggilingan.gudang2.service import Gudang2Error, pindah_tumpukan_ke_silo

    async with pg() as db:
        with pytest.raises(Gudang2Error) as e:
            await pindah_tumpukan_ke_silo(
                db, user=await db.get(User, g2["op"]), intake_id=g2["intake"],
                nama_silo="A", berat=9_999)
    pesan = str(e.value)
    assert "9999" in pesan.replace(".", "") and "29996" in pesan.replace(".", ""), pesan
    # Dan jalan keluarnya disebut — yang ditolak tanpa jalan keluar akan
    # dicoba lagi dengan cara yang sama.
    assert "kosongkan" in pesan.lower(), pesan


async def test_nol_bukan_kosong(pg, g2):
    """KOSONG dan NOL dua hal berbeda: kosong berarti "seluruh sisanya", nol
    berarti salah ketik. Menyamakan keduanya membuat satu ketukan Enter di
    kotak kosong memindahkan seluruh tumpukan tanpa diminta."""
    import inspect

    from app.web import api

    sumber = inspect.getsource(api.act_pindah_tumpukan_silo)
    assert "req.berat_kg is not None and float(req.berat_kg) <= 0" in sumber, \
        "rutenya tak membedakan kotak kosong dari angka nol"


# ───────────────────────── Rendemen ke operator ─────────────────────────

async def test_operator_melihat_rendemen_penyosohan_yang_sudah_selesai(pg, g2):
    """Rendemen adalah angka yang MENILAI pekerjaan operator. Menyimpannya
    hanya di meja Admin membuat yang dinilai tak pernah tahu nilainya.

    Kalimat penutupan memang menyebutnya, tetapi ia lewat dalam satu detik dan
    tak bisa dibuka lagi. Kartunya yang membuatnya masih terbaca besok pagi.
    """
    from app.database import now_local
    from app.models import Silo, User
    from app.penggilingan.gudang2.models import (PolishingOutputLog,
                                                 PolishingProcess,
                                                 PolishingSiloUsage)
    from app.services.berjalan import _kartu_sosoh_selesai

    async with pg() as db:
        silo = (await db.execute(
            __import__("sqlalchemy").select(Silo))).scalars().first()
        p = PolishingProcess(kode_proses="POL-RND-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=g2["op"])
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo.id,
                                  berat_awal_kg=10_000, berat_masuk_kg=0,
                                  berat_akhir_kg=0, berat_terpakai_kg=10_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="medium",
                                  berat_kg=8_840, waktu_update=now_local(),
                                  input_by=g2["op"]))
        await db.commit()

    async with pg() as db:
        kartu = await _kartu_sosoh_selesai(db)
    assert kartu, "penyosohan yang selesai tak meninggalkan satu kartu pun"
    k = kartu[0]
    assert k.utama == ("88.4", "%"), k.utama
    # TANPA TOMBOL: prosesnya selesai, tak ada langkah miliknya lagi. Kartu
    # bertombol yang ditekan lalu ditolak mengajari orang bahwa layarnya tak
    # bisa dipercaya.
    assert k.aksi is None and not k.tombol, "kartu selesai menawarkan tombol"


async def test_rendemen_satu_rumus_untuk_kartu_dan_penutupan(pg, g2):
    """Rumus yang disalin ke pembaca kedua akan berbeda pada perubahan
    berikutnya — dan yang berbeda adalah angka yang menilai pekerjaan orang."""
    import inspect

    from app.penggilingan.gudang2 import polishing

    sumber = inspect.getsource(polishing.selesai_penyosohan)
    assert "rendemen_proses(db" in sumber, \
        "penutupan menghitung rendemennya sendiri — dua rumus atas satu angka"
    assert "beras_total / pk_terpakai" not in sumber, sumber[-400:]
