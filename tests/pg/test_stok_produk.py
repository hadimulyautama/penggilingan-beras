"""Stok Produk — beras yang sudah keluar mesin akhirnya punya rumah.

Temuan QA 26 September 2026: beras yang keluar dari mesin sosoh tidak ada di
angka stok mana pun. `polishing_output_logs` dibaca tepat dua tempat di seluruh
repo, dan tak satu pun layar stok membacanya — beras baru MENJADI stok ketika
seseorang menjalankan "Catat packing". Di pabrik, jarak antara "sosoh selesai"
dan "packing dicatat" adalah jam, kadang hari; sepanjang waktu itu berton-ton
beras berdiri di lantai sementara aplikasi menyebut stoknya nol.

Keputusan pemilik: halaman "Stok Produk" sendiri, dan kartu hasil sosoh di
situ. Aksesnya semua orang KECUALI operator Gudang 1.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sosoh(pg, pemakai, pemasok):
    """Satu penyosohan SELESAI: 9.000 kg medium, belum dipacking sama sekali."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.models import (PkPurchaseBatch, PolishingOutputLog,
                                                 PolishingProcess, PolishingSiloUsage)
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
        p = PolishingProcess(kode_proses="POL-UJI-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=u.id)
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo.id,
                                  berat_awal_kg=10_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=10_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="medium",
                                  berat_kg=9_000, waktu_update=now_local(),
                                  input_by=u.id))
        await db.commit()
        return {"user": u.id, "kode": p.kode_proses, "proses_id": p.id}


async def test_beras_muncul_tanpa_perlu_dipacking_dulu(pg, sosoh):
    """Inti keluhannya. Sebelum ini: tak ada satu layar pun yang menyebutnya."""
    from app.services.stok import beras_curah

    async with pg() as db:
        baris = await beras_curah(db)
    assert len(baris) == 1, baris
    b = baris[0]
    assert b.kode_proses == "POL-UJI-01" and b.jenis == "medium"
    assert b.keluar_kg == 9_000 and b.dikemas_kg == 0 and b.sisa_kg == 9_000
    assert not b.berjalan


async def test_packing_memindahkan_bukan_menciptakan(pg, sosoh):
    """Sesudah dipacking sebagian: curah berkurang sebanyak itu, barang jadi
    bertambah sebanyak itu, dan jumlah keduanya tetap."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.stok import barang_jadi_g2, beras_curah

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_packing(db, user=u, kode_pol=sosoh["kode"],
                            kategori="beras_putih", grade="medium",
                            material_kode="biasa", ukuran=25,
                            jumlah_karung=100)          # 2.500 kg

    async with pg() as db:
        curah = await beras_curah(db)
        bj = await barang_jadi_g2(db)
    b = curah[0]
    assert b.dikemas_kg == 2_500 and b.sisa_kg == 6_500
    dikemas = sum(k["kg"] for k in bj.produk)
    assert dikemas == 2_500
    # Jumlah keduanya tetap: tak ada beras yang lahir atau lenyap.
    assert b.sisa_kg + dikemas == 9_000


async def test_packing_melebihi_curah_ditolak_dengan_angkanya(pg, sosoh):
    """Pagar yang sampai hari ini MUSTAHIL: tanpa angka asal, tak ada yang
    bisa dilanggar. Yang ada cuma peringatan sesudah commit."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import InventoryError, catat_packing

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        with pytest.raises(InventoryError) as e:
            await catat_packing(db, user=u, kode_pol=sosoh["kode"],
                                kategori="beras_putih", grade="medium",
                                material_kode="biasa", ukuran=25,
                                jumlah_karung=400)      # 10.000 kg > 9.000
    pesan = str(e.value)
    assert "9.000" in pesan and "10.000" in pesan, pesan

    # Dan tak ada yang tertulis: penolakannya SEBELUM menulis.
    from app.services.stok import barang_jadi_g2

    async with pg() as db:
        assert (await barang_jadi_g2(db)).produk == []


async def test_dua_jenis_dari_satu_proses_tak_saling_menimpa(pg, sosoh):
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.services.stok import beras_curah

    async with pg() as db:
        db.add(PolishingOutputLog(polishing_process_id=sosoh["proses_id"],
                                  jenis="premium", berat_kg=1_200,
                                  waktu_update=now_local(), input_by=sosoh["user"]))
        await db.commit()
    async with pg() as db:
        baris = {b.jenis: b.sisa_kg for b in await beras_curah(db)}
    assert baris == {"medium": 9_000, "premium": 1_200}


async def test_proses_yang_masih_berjalan_ditandai_belum_final(pg, sosoh):
    """Kartu penyosohan sudah jujur soal ini; blok stok yang menyebutnya
    seolah pasti akan membuat orang mengemas dua kali."""
    from sqlalchemy import select

    from app.models import User
    from app.penggilingan.gudang2.models import PolishingProcess
    from app.services.berjalan import untuk_operator_gudang2
    from app.services.stok import beras_curah

    async with pg() as db:
        p = (await db.execute(select(PolishingProcess))).scalars().one()
        p.status = "proses"
        p.waktu_selesai = None
        await db.commit()

    async with pg() as db:
        baris = await beras_curah(db)
        tanpa = await beras_curah(db, termasuk_berjalan=False)
        b = await untuk_operator_gudang2(db)
    assert len(baris) == 1 and baris[0].berjalan, "tak ditandai belum final"
    assert tanpa == [], "yang berjalan ikut ke daftar yang meminta yang final"
    # Dan ia TIDAK berkartu antrean: menagih pekerjaan atas angka yang masih
    # akan berubah membuat orang mengemas dua kali.
    assert not [x for x in b.menunggu if x.kelompok == "produk"]


async def test_kartu_antrean_dan_lencana_untuk_yang_sudah_selesai(pg, sosoh):
    """Halaman yang harus dibuka sendiri tak menjawab keluhan pemilik: yang
    hilang selama ini KABARNYA, bukan tempat menyimpannya."""
    from app.services.berjalan import untuk_operator_gudang2

    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    kartu = [x for x in b.menunggu if x.kelompok == "produk"]
    assert len(kartu) == 1, b.menunggu
    assert kartu[0].aksi == "catat_packing" and "9.000" in kartu[0].isi
    assert b.jumlah_produk == 1
    assert b.lencana()["PRODUK"] == 1


async def test_pintu_tertutup_hanya_bagi_operator_gudang1(pg, sosoh, pemasok):
    """Keputusan pemilik 26 September 2026: semua boleh, kecuali operator
    Gudang 1 — produknya sendiri (PK) sudah berkartu di layar Stok."""
    from sqlalchemy import select

    from app.models import User, Warehouse
    from app.services.berjalan import untuk

    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
            await db.flush()
        op1 = User(nama="Operator Selepan", role="operator", status="aktif",
                   default_warehouse_id=g1.id)
        adm = User(nama="Admin Produk", role="admin", status="aktif")
        db.add_all([op1, adm])
        await db.commit()
        await db.refresh(op1)
        await db.refresh(adm)

    async with pg() as db:
        b1 = await untuk(db, await db.get(User, op1.id))
        b2 = await untuk(db, await db.get(User, adm.id))
        b3 = await untuk(db, await db.get(User, sosoh["user"]))
    assert "stok_produk" in b1.lencana()["PINTU_MATI"], "operator G1 ditawari pintunya"
    assert "stok_produk" not in b2.lencana()["PINTU_MATI"], "Admin kehilangan pintunya"
    assert "stok_produk" not in b3.lencana()["PINTU_MATI"], "operator G2 kehilangan pintunya"
    # Lencananya ikut sampai ke Admin, bukan cuma ke yang mengerjakannya.
    assert b2.lencana()["PRODUK"] == 1


# ══════════════════════════════════════════════════════════════════════════
# SATU KARTU PER KATEGORI — keputusan pemilik 26 September 2026
#
#   "stok produk setiap kategori dijadikan 1 kartu saja dengan informasi inti
#    total jumlah stock. tetapi di setiap kartu ada informasi dari masing-masing
#    penyosohan dan informasi stock yang sudah keluar. artinya total hasil
#    penyosohan adalah total jumlah stock ditambah stock yang keluar."
#   "misal. premium dijadikan 1 kartu saja."
#
# Persamaannya PUNYA EMPAT SUKU, bukan dua — "stok" di Gudang 2 terbelah dua
# keadaan yang sangat berbeda, dan belahan "belum dikemas" itulah yang selama
# ini hilang:
#
#       hasil = belum dikemas + sudah dikemas + sudah keluar
# ══════════════════════════════════════════════════════════════════════════


async def _sosoh_lagi(pg, sosoh, kode: str, jenis: str, kg: float, *,
                      selesai: bool = True):
    """Satu penyosohan tambahan yang mengeluarkan `kg` `jenis`."""
    from app.database import now_local
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess

    async with pg() as db:
        p = PolishingProcess(
            kode_proses=kode, status="selesai" if selesai else "berjalan",
            waktu_mulai=now_local(),
            waktu_selesai=now_local() if selesai else None,
            created_by=sosoh["user"])
        db.add(p)
        await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis=jenis,
                                  berat_kg=kg, waktu_update=now_local(),
                                  input_by=sosoh["user"]))
        await db.commit()
        return p.id


def _persamaan(k) -> None:
    """Diperiksa DENGAN ANGKA, bukan dengan mata — permintaan QA.

    Dua hal sekaligus, dan keduanya wajib:
      · empat sukunya menutup: hasil == curah + dikemas + keluar;
      · KEPALA kartu sama dengan KAKINYA: sisa == dikemas + curah. Kartu yang
        kepalanya tak sama dengan kakinya akan dihitung ulang orang dengan
        kalkulator, sekali, lalu tak dipercaya lagi.
    """
    assert abs(k.hasil_kg - (k.curah_kg + k.dikemas_kg + k.keluar_kg)) < 0.5, (
        f"{k.jenis}: {k.hasil_kg} != {k.curah_kg} + {k.dikemas_kg} + {k.keluar_kg}")
    assert abs(k.sisa_kg - (k.dikemas_kg + k.curah_kg)) < 0.5, (
        f"{k.jenis}: kepala {k.sisa_kg} != kaki {k.dikemas_kg} + {k.curah_kg}")


async def test_satu_jenis_dari_tiga_penyosohan_tetap_satu_kartu(pg, sosoh):
    """Butir pemilik yang paling mudah dikerjakan salah: "misal. premium
    dijadikan 1 kartu saja." Tiga penyosohan, satu kartu, tiga baris rincian —
    dan totalnya sama dengan jumlah ketiganya."""
    from app.services.stok import stok_produk

    await _sosoh_lagi(pg, sosoh, "POL-UJI-02", "medium", 4_000)
    await _sosoh_lagi(pg, sosoh, "POL-UJI-03", "medium", 2_000)

    async with pg() as db:
        kartu = await stok_produk(db)
    assert [k.jenis for k in kartu] == ["medium"], \
        f"satu kategori harus satu kartu: {[k.jenis for k in kartu]}"
    k = kartu[0]
    assert len(k.hasil) == 3, f"rincian per penyosohan hilang: {k.hasil}"
    assert {r.kode for r in k.hasil} == {"POL-UJI-01", "POL-UJI-02", "POL-UJI-03"}
    assert k.hasil_kg == 15_000 == sum(r.kg for r in k.hasil)
    assert k.sisa_kg == 15_000 and k.curah_kg == 15_000 and k.dikemas_kg == 0
    _persamaan(k)


async def test_persamaan_empat_suku_bertahan_di_setiap_langkah(pg, sosoh):
    """Permintaan QA: persamaannya diuji SEBAGAI persamaan, untuk tiap kategori,
    pada tiap keadaan — bukan sekali di akhir.

    Langkahnya mengikuti perjalanan barangnya: keluar mesin → dikemas sebagian
    → dikirim sebagian. Suku yang bergeser berpindah ke suku lain; jumlahnya
    tak pernah berubah.
    """
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.penggilingan.inventory.outgoing import kirim_finished_goods
    from app.services.stok import stok_produk

    async def periksa():
        async with pg() as db:
            kartu = await stok_produk(db)
        for k in kartu:
            _persamaan(k)
        return {k.jenis: k for k in kartu}

    k = (await periksa())["medium"]
    assert (k.hasil_kg, k.curah_kg, k.dikemas_kg, k.keluar_kg) == (9_000, 9_000, 0, 0)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_packing(db, user=u, kode_pol=sosoh["kode"],
                            kategori="beras_putih", grade="medium",
                            material_kode="biasa", ukuran=25, jumlah_karung=200)
    k = (await periksa())["medium"]
    assert (k.curah_kg, k.dikemas_kg, k.keluar_kg) == (4_000, 5_000, 0)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await kirim_finished_goods(db, user=u, kategori="beras_putih",
                                   grade="medium", material_kode="biasa",
                                   ukuran=25, jumlah_karung=80,
                                   nama_pembeli="Toko Uji")
    k = (await periksa())["medium"]
    assert (k.curah_kg, k.dikemas_kg, k.keluar_kg) == (4_000, 3_000, 2_000)
    # Dan barang keluarnya BERKARTU, dengan pembelinya — "dari surat mana"
    # adalah pertanyaan yang muncul begitu pembeli menelepon.
    assert len(k.keluar) == 1 and k.keluar[0].kg == 2_000
    assert "Toko Uji" in (k.keluar[0].ket or "")
    assert k.keluar[0].kode.startswith("OUT-")


async def test_dua_jenis_jadi_dua_kartu_tak_saling_menimpa(pg, sosoh):
    """Satu proses, dua jenis beras → DUA kartu. Dulu keduanya lenyap sama
    sekali; yang lebih buruk daripada lenyap adalah salah satu menimpa yang
    lain dan angkanya terbaca benar."""
    from app.database import now_local
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.services.stok import stok_produk

    async with pg() as db:
        db.add(PolishingOutputLog(
            polishing_process_id=sosoh["proses_id"], jenis="premium",
            berat_kg=1_500, waktu_update=now_local(), input_by=sosoh["user"]))
        await db.commit()

    async with pg() as db:
        kartu = await stok_produk(db)
    assert [k.jenis for k in kartu] == ["premium", "medium"], \
        "urutannya beras terbaik lebih dulu"
    assert {k.jenis: k.hasil_kg for k in kartu} == {"premium": 1_500, "medium": 9_000}
    for k in kartu:
        _persamaan(k)


async def test_yang_dibukukan_melebihi_hasil_jadi_ALARM(pg, sosoh):
    """Dua keadaan yang BERLAWANAN ARAH, dan bedanya wajib terlihat:

      · selisih kecil POSITIF itu normal — beras curah yang belum dikemas;
      · selisih NEGATIF itu alarm — ada yang dibukukan tanpa pernah diproduksi.

    Satu tanda seru untuk dua keadaan berlawanan akan membuat operator
    mengabaikan dua-duanya.

    Ditulis langsung ke tabel, bukan lewat `catat_packing`: pintu itu sekarang
    MENOLAK packing yang melebihi curah (dan pagarnya sendiri ada di
    `test_packing_melebihi_curah_ditolak_dengan_angkanya`). Yang diuji di sini
    keadaan yang sudah tertulis sebelum pagar itu ada — dan kartunya wajib
    tetap jujur tentangnya, bukan menyembunyikannya.
    """
    from app.database import now_local
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.penggilingan.inventory.packaging import find_or_create_sku, get_standard
    from app.services.stok import stok_produk, toleransi_nominal

    async with pg() as db:
        sku = await find_or_create_sku(db, kategori="beras_putih",
                                       material_kode="biasa", ukuran=25)
        std = await get_standard(db, "medium")
        db.add(FinishedGoodsStock(
            product_sku_id=sku.id, rice_quality_standard_id=std.id if std else None,
            source_type="polishing", source_id=sosoh["proses_id"],
            jumlah_karung=400, berat_total_kg=10_000, waktu=now_local(),
            input_by=sosoh["user"]))
        await db.commit()

    async with pg() as db:
        k = next(x for x in await stok_produk(db) if x.jenis == "medium")
    assert k.curah_kg == -1_000, k.curah_kg
    assert k.alarm, "yang dibukukan melebihi hasil tapi tak jadi alarm"
    assert not k.beda_timbangan, "alarm tak boleh sekaligus disebut wajar"
    # Ambangnya sama dengan yang dipakai rekonsiliasi packing: 2% atau 50 kg.
    assert toleransi_nominal(9_000) == 180.0
    _persamaan(k)


async def test_selisih_sekecil_beda_timbangan_bukan_alarm(pg, sosoh):
    """Berat karung dihitung `jumlah × ukuran` — nominal — sedangkan hasil sosoh
    DITIMBANG. Keduanya hampir tak pernah sama persis, jadi minus kecil bukan
    kebocoran. Yang menyebutnya alarm mengajari orang mengabaikan alarm."""
    from app.database import now_local
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.penggilingan.inventory.packaging import find_or_create_sku, get_standard
    from app.services.stok import stok_produk

    async with pg() as db:
        sku = await find_or_create_sku(db, kategori="beras_putih",
                                       material_kode="biasa", ukuran=25)
        std = await get_standard(db, "medium")
        db.add(FinishedGoodsStock(
            product_sku_id=sku.id, rice_quality_standard_id=std.id if std else None,
            source_type="polishing", source_id=sosoh["proses_id"],
            jumlah_karung=362, berat_total_kg=9_050, waktu=now_local(),
            input_by=sosoh["user"]))                      # lebih 50 kg saja
        await db.commit()

    async with pg() as db:
        k = next(x for x in await stok_produk(db) if x.jenis == "medium")
    assert k.curah_kg == -50 and not k.alarm and k.beda_timbangan


async def test_proses_berjalan_tergambar_belum_final_di_kartu_kategori(pg, sosoh):
    """Kartu penyosohan sudah jujur soal ini; blok stok yang baru tak boleh
    lebih berani daripadanya. Berasnya memang berdiri di lantai — tetapi
    angkanya masih akan bertambah, dan yang menghitung stok atasnya akan
    mengemas dua kali."""
    from app.services.stok import stok_produk

    await _sosoh_lagi(pg, sosoh, "POL-UJI-09", "medium", 3_000, selesai=False)

    async with pg() as db:
        k = next(x for x in await stok_produk(db) if x.jenis == "medium")
    assert k.hasil_kg == 12_000, "yang masih berjalan tetap dihitung"
    assert k.belum_final_kg == 3_000, "tak ada yang menyebutnya belum final"
    jalan = [r for r in k.hasil if r.berjalan]
    assert len(jalan) == 1 and jalan[0].kode == "POL-UJI-09"
    assert "belum final" in (jalan[0].ket or "")
    _persamaan(k)


async def test_bekatul_berbentuk_lain_dan_tak_dipaksa_seragam(pg, sosoh):
    """Bekatul curah saja — ia tak pernah dikemas. Kartunya tak boleh menyebut
    "dikemas", dan angka stoknya wajib sama dengan `hitung_stok_bekatul`: satu
    pertanyaan, satu angka. Yang belum dicatat tetap terlihat, sebab celahnya
    sama bentuknya dengan beras curah."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import (catat_bekatul,
                                                           hitung_stok_bekatul)
    from app.services.stok import stok_produk

    await _sosoh_lagi(pg, sosoh, "POL-UJI-BK", "bekatul", 800)
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_bekatul(db, user=u, kode_pol="POL-UJI-BK", berat_kg=500)

    async with pg() as db:
        k = next(x for x in await stok_produk(db) if x.jenis == "bekatul")
        assert k.dikemas_kg == await hitung_stok_bekatul(db)
    assert k.curah_saja, "bekatul akan digambar seolah bisa dikemas"
    assert (k.hasil_kg, k.dikemas_kg, k.curah_kg) == (800, 500, 300)
    _persamaan(k)


async def test_pk_langsung_bukan_milik_halaman_ini(pg, sosoh):
    """PK Gudang 1 yang dijual tanpa disosoh adalah BAHAN, bukan produk.
    Menjumlahkannya di sini akan membuat kartu beras kehilangan stok atas
    barang yang bukan berasnya."""
    from app.database import now_local
    from app.penggilingan.inventory.models import OutgoingItem, OutgoingRecord
    from app.services.stok import stok_produk

    async with pg() as db:
        rec = OutgoingRecord(kode="OUT-UJI-PK", tanggal=date.today(),
                             waktu=now_local(), input_by=sosoh["user"],
                             nama_pembeli="Tengkulak")
        db.add(rec)
        await db.flush()
        db.add(OutgoingItem(outgoing_record_id=rec.id, item_type="pk_langsung",
                            berat_kg=5_000))
        await db.commit()

    async with pg() as db:
        kartu = await stok_produk(db)
    assert all(not any(r.kode == "OUT-UJI-PK" for r in k.keluar) for k in kartu)
    k = next(x for x in kartu if x.jenis == "medium")
    assert k.keluar_kg == 0 and k.sisa_kg == 9_000


async def test_halaman_menggambar_kartunya_beserta_empat_sukunya(pg, sosoh):
    """Pagar yang tak boleh dilewatkan: hitungan yang benar di layar yang gagal
    dirender sama saja tak ada. Dan galat templat cuma muncul saat DIRENDER —
    tak satu pun uji layanan menyentuhnya.

    Diperiksa juga bahwa keempat sukunya terbaca di halaman: kartu yang
    menyembunyikan belahan "belum dikemas" akan menunjukkan selisih yang dikira
    kebocoran, dan itulah cacat yang melahirkan halaman ini.
    """
    import httpx

    from app.main import app
    from app.models import ProduksiAkun, User
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_packing(db, user=u, kode_pol=sosoh["kode"],
                            kategori="beras_putih", grade="medium",
                            material_kode="biasa", ukuran=25, jumlah_karung=100)
    async with pg() as db:
        a = ProduksiAkun(user_id=sosoh["user"], username="uji_produk",
                         password_hash=S.hash_sandi("rahasia123"), status="aktif",
                         mode_perangkat=mode_bawaan("operator"))
        db.add(a)
        await db.commit()
        token = security.buat_token(a)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://uji") as c:
        c.cookies.set(security.NAMA_COOKIE, token)
        c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
        r = await c.get("/stok-produk")
    assert r.status_code == 200, r.text[:400]
    h = r.text
    assert "Beras Medium" in h, "kartu kategorinya tak tergambar"
    # Kepala kartu = SISA, bukan hasil penyosohan.
    assert "9.000" in h and "6.500" in h and "2.500" in h, h[-3000:]
    for kata in ("Hasil sosoh", "Dikemas", "Curah", "belum dikemas (curah)"):
        assert kata in h, f"suku '{kata}' hilang dari halaman"
    # Rincian per penyosohan ikut, lengkap dengan kodenya.
    assert "POL-UJI-01" in h
    # ── Dan kepalanya menyebut bahwa itu PERKIRAAN ──
    #
    # Daftar ini dipakai orang yang menangani keluhan pembeli untuk mencari
    # batch-nya. `outgoing_items` tak punya taut ke penyosohan maupun ke baris
    # stok yang dipakai, jadi begitu karung naik ke truk hubungannya putus —
    # FIFO di sini anggapan yang masuk akal, bukan penelusuran. Yang
    # menyangkanya catatan akan menyalahkan penyosohan yang salah, dan di beras
    # itu berujung ke pemasok dan ke uang.
    assert "Perkiraan asal stok (FIFO)" in h, \
        "daftar perkiraan dipajang seolah catatan pasti"


# ══════════════════════════════════════════════════════════════════════════
# BORANG PACKING — berhenti menanyakan yang sudah diketahui kartunya
#
# Keluhan pemilik 28 September 2026, dua kalimat, satu sebab:
#
#   "kartu beras menunggu dipacking sudah menunjukkan mutu berasnya. di catat
#    barang jadinya untuk apa mutu juga dipilih? di bagian pemilihan produk dan
#    kemasan pun ada keterangan beras putih, menir, reject, dll. cukup jenis
#    kemasannya dan ukuran kemasannya."
#
#   "di kartu beras menunggu di packting adalah premium ya di halaman melayang
#    catat packing barang jadi juga harus langsung tau kalau itu beras premium,
#    beras b, reject, menir dll"
#
# Borangnya dulu bertanya EMPAT kali untuk satu pekerjaan — proses, produk +
# kemasan, merk, mutu — dan tiga dari empat sudah dijawab oleh kartu yang
# ditekan orangnya. Sebabnya penunjuknya cuma membawa kode proses, jadi
# JENISNYA hilang di perjalanan.
# ══════════════════════════════════════════════════════════════════════════


async def test_penunjuk_packing_membawa_lot_dan_jenisnya(pg, sosoh):
    """Kartu dan daftar harus berbicara dengan BENTUK YANG SAMA. Kalau tidak,
    kartu mengirim nilai yang tak ada di daftar, penguncian batal, dan orangnya
    kembali disuruh memilih benda yang baru saja ia tekan."""
    from app.models import User
    from app.services.berjalan import _kartu_beras_curah
    from app.web import aksi_inventory as inv

    async with pg() as db:
        kartu = await _kartu_beras_curah(db)
        daftar = await inv.beras_belum_dikemas(
            user=await db.get(User, sosoh["user"]))

    assert len(kartu) == 1 and kartu[0].nilai == "POL-UJI-01|medium"
    # Tombolnya membawa nilai yang SAMA dengan kartunya.
    assert kartu[0].pilihan[0][3] == kartu[0].nilai
    assert [d["value"] for d in daftar] == ["POL-UJI-01|medium"]
    # Dan labelnya menyebut jenisnya dengan kata yang dibaca orang.
    assert "Beras Medium" in daftar[0]["label"], daftar[0]["label"]
    assert "9.000" in daftar[0]["label"]


async def test_borang_packing_tak_bertanya_mutu_lagi(pg, sosoh):
    """Yang dijaga BENTUK BORANGNYA, sebab inilah yang dikeluhkan. Mutu dan
    kategori tak boleh kembali jadi pertanyaan: keduanya sudah terbawa
    penunjuknya."""
    from app.web.aksi_inventory import spesifikasi

    spek = next(a for a in spesifikasi(g2=True, fin=False)
                if a["id"] == "catat_packing")
    medan = [f["name"] for f in spek["fields"]]
    assert medan == ["sumber", "kemasan", "merk", "jumlah_karung"], medan
    assert "grade" not in medan and "produk" not in medan and "kode_pol" not in medan
    # Penunjuknya bertipe yang bisa dikunci kartu, dan kemasannya bergantung
    # padanya — daftar kemasan yang berdiri sendiri akan menawarkan karung yang
    # tak sah untuk barang itu.
    assert spek["fields"][0]["type"] == "remote"
    assert spek["fields"][1]["induk"] == "sumber"


async def test_daftar_kemasan_menyebut_karungnya_saja(pg, sosoh):
    """"cukup jenis kemasannya dan ukuran kemasannya."

    Daftar lamanya mengulang nama barangnya di tiap baris ("Beras putih ·
    karung laminasi 25 kg", delapan kali) padahal barangnya sudah ditunjuk —
    dan daftar yang mengulang hal sama di tiap baris memaksa mata membaca
    bagian yang berbeda saja, yang justru tercetak paling belakang.
    """
    from app.models import User
    from app.web import aksi_inventory as inv

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        beras = await inv.kemasan_untuk(induk="POL-UJI-01|medium", user=u)
        menir = await inv.kemasan_untuk(induk="POL-UJI-01|menir", user=u)

    assert beras, "beras putih tak punya satu kemasan pun"
    for baris in beras:
        assert "Beras" not in baris["label"], baris["label"]
        assert "kg" in baris["label"]
    # Dan daftarnya BERBEDA menurut barangnya — itu gunanya bergantung induk.
    assert {b["value"] for b in beras} != {m["value"] for m in menir}
    # Tanpa induk: kosong, bukan seluruh kemungkinan.
    async with pg() as db:
        assert await inv.kemasan_untuk(
            induk="", user=await db.get(User, sosoh["user"])) == []


async def test_packing_bentuk_baru_memindahkan_berasnya(pg, sosoh):
    """Bentuk kiriman berubah; yang dicatat tidak boleh berubah."""
    from app.models import User
    from app.web import aksi_inventory as inv
    from app.services.stok import beras_curah

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        r = await inv.act_catat_packing(
            inv.PackingReq(sumber="POL-UJI-01|medium", kemasan="biasa|25",
                           jumlah_karung=100), user=u)
    assert r["ok"] and "2.500" in r["pesan"], r["pesan"]

    async with pg() as db:
        b = (await beras_curah(db))[0]
    assert b.dikemas_kg == 2_500 and b.sisa_kg == 6_500


async def test_bentuk_kiriman_lama_tetap_diterima(pg, sosoh):
    """Halaman di ponsel berumur panjang: lembar yang sudah terbuka di layar
    orang saat versi baru terbit akan mengirim bentuk lama, dan yang menekan
    Simpan tak punya cara mengetahui bahwa borangnya sudah basi. Yang berhenti
    cuma MENAWARKANNYA."""
    from app.models import User
    from app.services.stok import beras_curah
    from app.web import aksi_inventory as inv

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        r = await inv.act_catat_packing(
            inv.PackingReq(kode_pol="POL-UJI-01", produk="beras_putih|biasa|25",
                           grade="medium", jumlah_karung=40), user=u)
    assert r["ok"], r
    async with pg() as db:
        assert (await beras_curah(db))[0].dikemas_kg == 1_000


async def test_kemasan_tak_sah_ditolak_walau_daftarnya_dilewati(pg, sosoh):
    """Yang mengirim POST adalah perangkat, dan isian perangkat tak pernah jadi
    alasan untuk melewati pemeriksaan."""
    from fastapi import HTTPException

    from app.models import User
    from app.web import aksi_inventory as inv

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        with pytest.raises(HTTPException):
            await inv.act_catat_packing(
                inv.PackingReq(sumber="POL-UJI-01|medium", kemasan="biasa|7",
                               jumlah_karung=1), user=u)
        with pytest.raises(HTTPException):
            await inv.act_catat_packing(
                inv.PackingReq(sumber="POL-UJI-01", kemasan="biasa|25",
                               jumlah_karung=1), user=u)


async def test_barang_keluar_dipilih_dari_stok_yang_ada(pg, sosoh):
    """Keputusan pemilik 28 September 2026, sejalan dengan borang packing.

    "Barang jadi keluar" dulu bertanya TIGA kali untuk satu barang — produk +
    kemasan, merk, lalu mutu — dan ketiganya pertanyaan tentang benda yang
    SUDAH ADA di gudang. Daftar tiga tingkat atas benda yang bisa dilihat
    sendiri adalah tiga kesempatan memilih kombinasi yang stoknya nol.
    """
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.web import aksi_inventory as inv

    spek = next(a for a in inv.spesifikasi(g2=False, fin=True)
                if a["id"] == "kirim_barang_jadi")
    medan = [f["name"] for f in spek["fields"]]
    assert medan[:2] == ["stok", "jumlah_karung"], medan
    assert "grade" not in medan and "produk" not in medan and "merk" not in medan

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_packing(db, user=u, kode_pol=sosoh["kode"],
                            kategori="beras_putih", grade="medium",
                            material_kode="biasa", ukuran=25, jumlah_karung=100)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        u.role = "admin"                       # daftar ini milik yang lihat uang
        await db.commit()
        daftar = await inv.stok_barang_jadi(user=u)
    assert len(daftar) == 1, daftar
    # Satu baris menjawab ketiga pertanyaan lama sekaligus, berikut stoknya.
    label = daftar[0]["label"]
    assert "Medium" in label and "25 kg" in label and "100 karung" in label, label
    sku_id, std_id = daftar[0]["value"].split("|")
    assert sku_id.isdigit() and std_id.isdigit()

    # Dan kirimannya mencatat barang yang SAMA.
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        r = await inv.act_kirim_barang_jadi(
            inv.KirimBarangJadiReq(stok=daftar[0]["value"], jumlah_karung=40,
                                   nama_pembeli="Toko Uji"), user=u)
    assert r["ok"], r
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        sisa = await inv.stok_barang_jadi(user=u)
    assert "60 karung" in sisa[0]["label"], sisa[0]["label"]


async def test_bekatul_curah_tak_ditawarkan_sebagai_barang_berkarung(pg, sosoh):
    """Ia curah dan punya aksinya sendiri; menawarkannya di daftar berkarung
    akan membuat orang mengirim "0 karung bekatul"."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_bekatul
    from app.web import aksi_inventory as inv

    await _sosoh_lagi(pg, sosoh, "POL-UJI-BK2", "bekatul", 700)
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_bekatul(db, user=u, kode_pol="POL-UJI-BK2", berat_kg=700)
        u.role = "admin"
        await db.commit()
    async with pg() as db:
        daftar = await inv.stok_barang_jadi(user=await db.get(User, sosoh["user"]))
    assert not [d for d in daftar if "ekatul" in d["label"]], daftar


# ══════════════════════════════════════════════════════════════════════════
# DAFTAR YANG MENYUSUT BERSAMA BARANGNYA — temuan QA 28 September 2026
#
# Kepala kartu sudah benar (sisa 3.000 kg) tetapi daftar "Hasil penyosohan"
# tetap 8 baris berjumlah 24.000 kg: satu kartu memuat dua angka yang
# bertentangan, dan yang besar dicetak sebagai daftar rinci yang terlihat
# berwibawa. Pada 500 penyosohan daftarnya 508 baris, halamannya 119 KB dan
# 1,77 detik — dan itu baru SATU dari sembilan jenis.
# ══════════════════════════════════════════════════════════════════════════


async def _jual(pg, sosoh, kg_per_nota, *, n=1):
    """Kirim barang jadi `n` kali, tiap kali `kg_per_nota` kg (karung 25 kg)."""
    from app.models import User
    from app.penggilingan.inventory.outgoing import kirim_finished_goods

    for i in range(n):
        async with pg() as db:
            u = await db.get(User, sosoh["user"])
            await kirim_finished_goods(
                db, user=u, kategori="beras_putih", grade="medium",
                material_kode="biasa", ukuran=25,
                jumlah_karung=int(kg_per_nota // 25),
                nama_pembeli=f"Toko {i + 1}")


async def test_fifo_daftar_menyusut_dan_berjumlah_sama_dengan_kepalanya(pg, sosoh):
    """Skenario QA persis: 8 penyosohan @ 3 ton, dikemas semua, dijual 21 ton.

    Sisanya 3 ton, dan menurut FIFO ia seluruhnya dari penyosohan TERAKHIR —
    jadi daftarnya satu baris, bukan delapan.
    """
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.stok import stok_produk

    # POL-UJI-01 sudah ada (9.000 kg medium) — dipakai ulang jadi 3.000 kg
    # supaya angkanya sama dengan laporan QA.
    from sqlalchemy import update

    from app.penggilingan.gudang2.models import PolishingOutputLog

    async with pg() as db:
        await db.execute(update(PolishingOutputLog).values(berat_kg=3_000))
        await db.commit()
    for i in range(2, 9):
        await _sosoh_lagi(pg, sosoh, f"POL-UJI-{i:02d}", "medium", 3_000)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        k = next(x for x in await stok_produk(db) if x.jenis == "medium")
    assert k.hasil_kg == 24_000 and len(k.hasil) == 8

    # Dikemas seluruhnya, lalu dijual 21 ton lewat 7 nota.
    for i in range(1, 9):
        async with pg() as db:
            u = await db.get(User, sosoh["user"])
            await catat_packing(db, user=u, kode_pol=f"POL-UJI-{i:02d}",
                                kategori="beras_putih", grade="medium",
                                material_kode="biasa", ukuran=25,
                                jumlah_karung=120)          # 3.000 kg
    await _jual(pg, sosoh, 3_000, n=7)

    async with pg() as db:
        k = next(x for x in await stok_produk(db) if x.jenis == "medium")

    # Kepalanya TIDAK berubah — QA menegaskan angka kepala sudah benar.
    assert (k.hasil_kg, k.keluar_kg, k.sisa_kg) == (24_000, 21_000, 3_000)
    # Daftarnya yang menyusut, dan ia berjumlah SAMA dengan kepalanya.
    assert [r.kode for r in k.hasil] == ["POL-UJI-08"], [r.kode for r in k.hasil]
    assert sum(r.kg for r in k.hasil) == k.sisa_kg
    assert k.hasil_lagi == 0


async def test_fifo_menampilkan_sisa_baris_yang_termakan_sebagian(pg, sosoh):
    """Yang termakan separuh ditampilkan SISANYA, bukan angka aslinya — kalau
    tidak, jumlah daftar melampaui kepala kartu dan kartunya kembali
    bertentangan dengan dirinya sendiri."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.stok import stok_produk

    await _sosoh_lagi(pg, sosoh, "POL-UJI-20", "medium", 3_000)
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        for kode, karung in (("POL-UJI-01", 360), ("POL-UJI-20", 120)):
            await catat_packing(db, user=u, kode_pol=kode,
                                kategori="beras_putih", grade="medium",
                                material_kode="biasa", ukuran=25,
                                jumlah_karung=karung)
    await _jual(pg, sosoh, 10_000)            # makan POL-01 (9.000) + 1.000

    async with pg() as db:
        k = next(x for x in await stok_produk(db) if x.jenis == "medium")
    assert k.sisa_kg == 2_000
    assert [(r.kode, r.kg) for r in k.hasil] == [("POL-UJI-20", 2_000)]
    assert sum(r.kg for r in k.hasil) == k.sisa_kg


async def test_daftar_berbatas_dan_sisanya_diringkas(pg, sosoh):
    """Tanpa batas, 500 penyosohan jadi 508 baris pada satu kartu. Sisanya
    DIRINGKAS, bukan dilipat: melipat baris tetap menuntut seluruhnya dikirim
    ke telepon, dan yang diukur QA adalah byte-nya."""
    from app.services.stok import BATAS_RINCI_HASIL, stok_produk

    # Fixture `sosoh` sudah menyumbang SATU penyosohan; dua di atas batas.
    for i in range(2, 2 + BATAS_RINCI_HASIL + 2):
        await _sosoh_lagi(pg, sosoh, f"POL-BNY-{i:02d}", "medium", 1_000)

    async with pg() as db:
        k = next(x for x in await stok_produk(db) if x.jenis == "medium")
    assert len(k.hasil) == BATAS_RINCI_HASIL
    assert k.hasil_lagi == 3, k.hasil_lagi
    # Yang diringkas tetap terhitung: daftar + ringkasan = kepala kartu.
    assert sum(r.kg for r in k.hasil) + k.hasil_lagi_kg == k.sisa_kg


async def test_memotong_daftar_keluar_tak_memotong_persamaannya(pg, sosoh):
    """"ANGKA `keluar_kg` DI KEPALA KARTU TETAP SELURUHNYA" — kalau suku keluar
    ikut terpotong, persamaan hasil = keluar + dikemas + curah patah, dan
    seluruh kartu ini berdiri di atas persamaan itu."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.stok import BATAS_RINCI_KELUAR, stok_produk

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_packing(db, user=u, kode_pol=sosoh["kode"],
                            kategori="beras_putih", grade="medium",
                            material_kode="biasa", ukuran=25, jumlah_karung=360)
    n = BATAS_RINCI_KELUAR + 3
    await _jual(pg, sosoh, 500, n=n)          # n nota @ 500 kg

    async with pg() as db:
        k = next(x for x in await stok_produk(db) if x.jenis == "medium")
    assert len(k.keluar) == BATAS_RINCI_KELUAR
    assert k.keluar_lagi == 3
    assert k.keluar_kg == 500 * n, "kepala kartu ikut terpotong"
    assert sum(r.kg for r in k.keluar) + k.keluar_lagi_kg == k.keluar_kg
    _persamaan(k)


async def test_bentuk_borongan_sama_dengan_bentuk_tunggal(pg, sosoh):
    """`output_sosoh_banyak` memakai aturan yang SAMA dengan `output_sosoh`.

    Bentuk borongan yang menyusun aturannya sendiri (misalnya `MAX(id)`) akan
    berselisih dengan bentuk tunggalnya pada baris yang waktunya diketik
    mundur — dan yang salah adalah yang lebih jarang dibaca orang.
    """
    from app.database import now_local
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.services.stok import output_sosoh, output_sosoh_banyak
    from sqlalchemy import select

    # Baris kedua: id LEBIH BESAR tetapi waktunya LEBIH TUA.
    from datetime import timedelta

    async with pg() as db:
        db.add(PolishingOutputLog(
            polishing_process_id=sosoh["proses_id"], jenis="medium",
            berat_kg=111, waktu_update=now_local() - timedelta(days=1),
            input_by=sosoh["user"]))
        await db.commit()

    async with pg() as db:
        ids = list((await db.execute(select(PolishingProcess.id))).scalars().all())
        borongan = await output_sosoh_banyak(db, ids)
        for pid in ids:
            assert await output_sosoh(db, pid) == borongan.get(pid, {}), pid
        # Dan tanpa daftar id = seluruhnya.
        assert await output_sosoh_banyak(db) == borongan
