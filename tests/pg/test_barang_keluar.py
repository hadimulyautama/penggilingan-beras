"""Barang keluar berperintah: Admin memerintah · operator memuat · Admin verifikasi.

Permintaan pemilik 28 September 2026. Rantai tiga langkah, dan berkas ini
menjaga hal-hal yang tak terlihat di layar sampai seseorang menekannya dua
kali — sama seperti rantai permintaan PK yang jadi contohnya.

Yang paling penting di antaranya: STOK BERKURANG SAAT DIMUAT. Bukan saat
diperintah (barangnya masih di gudang) dan bukan saat diverifikasi (truknya
sudah pergi berjam-jam sebelumnya). Titik-pindah yang bergeser satu langkah
membuat seluruh angka stok salah pada hari yang sibuk, dan tak ada satu pun
pesan galat yang menyebutnya.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def gudang(pg):
    """Stok 400 karung Beras Medium 25 kg (10.000 kg), satu Admin, satu operator G2."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Silo, Supplier, User, Warehouse
    from app.penggilingan.gudang2.models import (PkPurchaseBatch, PolishingOutputLog,
                                                 PolishingProcess, PolishingSiloUsage)
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.peran import PERAN_ADMIN_KEATAS
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
            db.add(g2)
            await db.flush()
        silo = Silo(nama_silo="Silo A", warehouse_id=g2.id)
        op = User(nama="Op Polesan", role="operator", status="aktif",
                  default_warehouse_id=g2.id)
        adm = User(nama="Admin Uji", role=PERAN_ADMIN_KEATAS[-1], status="aktif")
        s = Supplier(nama_supplier="UD Sumber")
        db.add_all([silo, op, adm, s])
        await db.flush()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-BK-01", supplier_id=s.id, berat_total_kg=20_000,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=op.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        p = PolishingProcess(kode_proses="POL-BK-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=op.id)
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo.id,
                                  berat_awal_kg=20_000, berat_masuk_kg=0,
                                  berat_akhir_kg=0, berat_terpakai_kg=20_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="medium",
                                  berat_kg=10_000, waktu_update=now_local(),
                                  input_by=op.id))
        await db.commit()
        await db.refresh(op)
        await catat_packing(db, user=op, kode_pol=p.kode_proses,
                            kategori="beras_putih", grade="medium",
                            material_kode="biasa", ukuran=25, jumlah_karung=400)
        sku_id, std_id = (await db.execute(text_sku())).first()
        return {"op": op.id, "adm": adm.id, "sku": sku_id, "std": std_id,
                "silo": silo.id}


def text_sku():
    from sqlalchemy import select

    from app.penggilingan.inventory.models import FinishedGoodsStock
    return select(FinishedGoodsStock.product_sku_id,
                  FinishedGoodsStock.rice_quality_standard_id).limit(1)


async def _stok(pg, g) -> float:
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    async with pg() as db:
        return float((await hitung_stok_finished_goods(db, g["sku"], g["std"]))["kg"])


async def _perintah(pg, g, karung=100, pembeli="Toko Makmur"):
    from app.models import User
    from app.services import barang_keluar as bk
    # `pembeli` dulu dikirim sebagai NAMA ketik-bebas; kotak itu dicabut 11
    # Oktober 2026 (keputusan pemilik: "field pembeli baru hapus saja") —
    # kini wajib tertaut ke master `pelanggan`, jadi helper ini membuatnya
    # dulu supaya seluruh pemanggil lama (yang cuma peduli NAMANYA, bukan
    # tautannya) tetap jalan tanpa diubah satu-satu.
    pid = await _pelanggan(pg, pembeli)
    async with pg() as db:
        return await bk.buat_perintah(
            db, user=await db.get(User, g["adm"]),
            baris=[bk.BarisPerintah(tipe="finished_goods", sku_id=g["sku"],
                                    std_id=g["std"], jumlah_karung=karung)],
            pelanggan_id=pid, no_polisi="B 1234 XY")


async def test_perintah_belum_mengurangi_stok(pg, gudang):
    """Barangnya masih berdiri di gudang sampai ada yang memuatnya.

    Perintah yang langsung memotong stok membuat gudang terbaca kosong
    sementara karungnya masih bertumpuk — dan operator yang melihat stok nol
    akan berhenti mengemas.
    """
    awal = await _stok(pg, gudang)
    assert awal == 10_000
    await _perintah(pg, gudang, karung=100)
    assert await _stok(pg, gudang) == awal, "perintah sudah memotong stok"


async def test_stok_berkurang_tepat_saat_dimuat(pg, gudang):
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                            rec_id=r.rec.id)
    assert await _stok(pg, gudang) == 7_500, "stok tak berkurang saat dimuat"

    # Verifikasi TIDAK memotong lagi — dua potongan atas satu muatan.
    async with pg() as db:
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=r.rec.id)
    assert await _stok(pg, gudang) == 7_500, "verifikasi memotong stok kedua kalinya"


async def test_satu_transaksi_memuat_beberapa_macam_barang(pg, gudang):
    """Inti permintaan pemilik: "1 transaksi bisa beberapa macam barang".

    Sebelum hari ini satu truk berisi beras + broken + menir melahirkan TIGA
    kode OUT- yang berbeda — tiga baris di kartu Stok Produk, dan tiga
    pencocokan untuk satu tiket timbang.
    """
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.penggilingan.inventory.finished_goods import catat_bekatul
    from app.services import barang_keluar as bk
    from sqlalchemy import select

    async with pg() as db:
        proc = (await db.execute(select(PolishingProcess))).scalars().first()
        db.add(PolishingOutputLog(polishing_process_id=proc.id, jenis="bekatul",
                                  berat_kg=2_000, waktu_update=now_local(),
                                  input_by=gudang["op"]))
        await db.commit()
        await catat_bekatul(db, user=await db.get(User, gudang["op"]),
                            kode_pol=proc.kode_proses, berat_kg=2_000)

    r = await _perintah(pg, gudang, karung=40)
    async with pg() as db:
        r2 = await bk.tambah_baris(
            db, user=await db.get(User, gudang["adm"]), rec_id=r.rec.id,
            baris=bk.BarisPerintah(tipe="byproduct_curah", jenis="bekatul",
                                   berat_kg=500))
    assert len(r2.baris) == 2, "barang kedua tak masuk ke transaksi yang sama"
    assert r2.rec.kode == r.rec.kode, "lahir kode OUT- kedua untuk satu truk"


async def test_tambah_baris_pesanan_jasa_tak_lagi_lolos_memakai_stok_pabrik(pg, gudang):
    """Laporan lapangan 10 Oktober 2026, arah KEBALIKAN dari
    `test_tambah_baris_pesanan_sendiri_tak_lagi_ditolak_salah_arah`
    (`test_pk_g2_keluar.py`): `tambah_baris` dulu TIDAK PERNAH menurunkan
    `baris.jasa_id` dari `rec.jasa_id`, jadi `tersedia()` selalu memeriksa
    `jasa_id=None` (stok PABRIK) apa pun pemilik transaksinya. Akibatnya
    menambahkan SKU yang jasa_a SAMA SEKALI TAK PUNYA ke perintah PENGAMBILAN
    JASA-nya sendiri dulu LOLOS (memakai stok pabrik yang 400 karung), padahal
    seharusnya ditolak — barang itu bukan milik pesanan ini.
    """
    from app.database import now_local
    from app.models import Jasa, Pelanggan, User
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingOutputLog
    from app.penggilingan.inventory.finished_goods import catat_bekatul
    from app.services import barang_keluar as bk

    async with pg() as db:
        bu_sri = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(bu_sri)
        await db.flush()
        jasa_a = Jasa(kode="JAS-2610-020", pelanggan_id=bu_sri.id, status="berjalan")
        db.add(jasa_a)
        await db.flush()
        proc = PolishingProcess(
            kode_proses="POL-TB-01", jasa_id=jasa_a.id, status="selesai",
            waktu_mulai=now_local(), waktu_selesai=now_local(),
            created_by=gudang["op"])
        db.add(proc)
        await db.flush()
        db.add(PolishingOutputLog(
            polishing_process_id=proc.id, jenis="bekatul", berat_kg=3_000,
            waktu_update=now_local(), input_by=gudang["op"]))
        await db.commit()
        jasa_id = jasa_a.id
        await catat_bekatul(db, user=await db.get(User, gudang["op"]),
                            kode_pol=proc.kode_proses, berat_kg=3_000)

    # Pengambilan memakai hasil sosoh milik jasa sendiri. PK Gudang 2 kini
    # dilarang dikirim langsung; pagar kepemilikan tetap harus diuji melalui
    # barang yang memang boleh dipesan, bukan gagal sebelum mencapai pagar.
    async with pg() as db:
        r = await bk.buat_perintah(
            db, user=await db.get(User, gudang["adm"]), jasa_id=jasa_id,
            baris=[bk.BarisPerintah(tipe="byproduct_curah", jenis="bekatul",
                                    berat_kg=500)])
        rec_id = r.rec.id

    # SKU pabrik (400 karung tersedia) ditambahkan ke perintah jasa_a ini —
    # jasa_a sendiri TAK PUNYA satu karung pun SKU ini.
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.tambah_baris(
                db, user=await db.get(User, gudang["adm"]), rec_id=rec_id,
                baris=bk.BarisPerintah(tipe="finished_goods", sku_id=gudang["sku"],
                                       std_id=gudang["std"], jumlah_karung=50))
    assert "tinggal 0 kg" in str(e.value), (
        f"harusnya ditolak sebab jasa_a tak punya SKU ini sama sekali: {e.value}")


async def test_perintah_melebihi_stok_ditolak_dengan_angkanya(pg, gudang):
    """Yang ditolak tanpa angka akan mencoba lagi dengan tebakan."""
    from app.services import barang_keluar as bk

    with pytest.raises(bk.BarangKeluarError) as e:
        await _perintah(pg, gudang, karung=500)          # 12.500 kg > 10.000
    assert "10.000" in str(e.value), str(e.value)


async def test_dua_perintah_tak_boleh_membagi_stok_yang_sama(pg, gudang):
    """Perintah yang belum dimuat IKUT DIKURANGKAN dari stok yang bisa keluar.

    Tanpa itu, Admin menerbitkan dua perintah atas 10.000 kg yang sama; keduanya
    lolos, dan yang kedua baru gagal berjam-jam kemudian — di tangan operator,
    di depan truk yang sudah datang.
    """
    from app.services import barang_keluar as bk

    await _perintah(pg, gudang, karung=300)              # 7.500 kg
    with pytest.raises(bk.BarangKeluarError) as e:
        await _perintah(pg, gudang, karung=200, pembeli="Toko Lain")  # 5.000 kg
    assert "2.500" in str(e.value), str(e.value)


async def test_byproduct_curah_tak_lagi_memakai_stok_bekatul_untuk_jenis_lain(pg, gudang):
    """Pesan kerja 11 butir 1 — cacat pabrik yang SEDANG BERJALAN hari ini.

    `tersedia()` untuk `byproduct_curah` dulu SELALU memanggil
    `hitung_stok_bekatul(db)`, apa pun `b.jenis`-nya diminta. Dibuktikan di
    sandbox pemilik: bekatul 1.000 kg, menir NOL, dan `tersedia('menir')`
    menjawab 1.000 kg berlabel "Menir" — Admin bisa menerbitkan perintah
    muat menir yang tak ada satu kilo pun, tanpa satu pun pesan.

    Uji ini yang paling penting di butir 1 (per pesan kerjanya sendiri):
    bekatul 1.000 kg, menir NOL, `tersedia('menir')` WAJIB 0 kg.
    """
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.penggilingan.inventory.finished_goods import catat_bekatul
    from app.services import barang_keluar as bk
    from sqlalchemy import select

    async with pg() as db:
        proc = (await db.execute(select(PolishingProcess))).scalars().first()
        db.add(PolishingOutputLog(polishing_process_id=proc.id, jenis="bekatul",
                                  berat_kg=1_000, waktu_update=now_local(),
                                  input_by=gudang["op"]))
        await db.commit()
        # Bekatul pabrik 1.000 kg — SATU-SATUNYA hasil samping yang tercatat.
        # Menir TIDAK PERNAH dicatat sama sekali di uji ini, sengaja: absennya
        # barisnya DI `byproduct_stock` adalah "menir NOL" yang sebenarnya.
        await catat_bekatul(db, user=await db.get(User, gudang["op"]),
                            kode_pol=proc.kode_proses, berat_kg=1_000)

    pid = await _pelanggan(pg, "Toko Makmur")
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.buat_perintah(
                db, user=await db.get(User, gudang["adm"]),
                baris=[bk.BarisPerintah(tipe="byproduct_curah", jenis="menir",
                                        berat_kg=1)],
                pelanggan_id=pid, no_polisi="B 1234 XY")
    assert "tinggal 0 kg" in str(e.value), str(e.value)
    assert "1.000" not in str(e.value), \
        "stok bekatul masih bocor ke penolakan menir: " + str(e.value)

    # Bekatulnya sendiri TETAP terbaca benar — perbaikannya tidak menghapus
    # jalan yang sudah bekerja, cuma membetulkan jenis lain.
    async with pg() as db:
        r = await bk.buat_perintah(
            db, user=await db.get(User, gudang["adm"]),
            baris=[bk.BarisPerintah(tipe="byproduct_curah", jenis="bekatul",
                                    berat_kg=1_000)],
            pelanggan_id=pid, no_polisi="B 1234 XY")
    assert r.rec.kode


async def test_muat_kurang_diterima_dan_sisanya_hangus(pg, gudang):
    """Muatan sungguhan memang berselisih — karung rusak, truk penuh lebih cepat.

    Sisanya HANGUS, tidak menggantung: perintah yang tersisa separuh akan
    berdiri di antrean sampai seseorang mengingatnya, lalu dimuat seminggu
    kemudian ke truk yang salah.
    """
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=100)
    baris = r.baris[0]
    async with pg() as db:
        await bk.catat_muatan(db, user=await db.get(User, gudang["op"]),
                              item_id=baris.id, jumlah_karung=80)
        await bk.selesai_muat(db, user=await db.get(User, gudang["op"]),
                              rec_id=r.rec.id, sebab="Truk penuh; sisa tidak terkirim")
    assert await _stok(pg, gudang) == 8_000                # 400−80 karung
    async with pg() as db:
        rec, items = (await bk.daftar(db))[0]
    assert float(items[0].berat_perintah_kg) == 2_500, "perintah ikut tertimpa"
    assert float(items[0].berat_kg) == 2_000, "yang dimuat tak tercatat"


async def test_muat_melebihi_perintah_ditolak(pg, gudang):
    """Yang melebihi perintah berarti barang keluar tanpa yang memerintahkan —
    dan itu justru yang dihentikan seluruh rantai ini."""
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.catat_muatan(db, user=await db.get(User, gudang["op"]),
                                  item_id=r.baris[0].id, jumlah_karung=120)
    assert "2.500" in str(e.value) and "3.000" in str(e.value), str(e.value)


async def test_dua_operator_menekan_muat_bersamaan_hanya_satu_menang(pg, gudang):
    """Dua SESI sungguhan, bukan dua panggilan berurutan.

    Yang berurutan lolos walau pagarnya tak ada — dan pagarnya di sini `FOR
    UPDATE` pada barisnya: penekan kedua menunggu yang pertama commit, membaca
    ulang keadaannya, lalu ditolak dengan kalimat yang menyebut SIAPA yang
    mendahuluinya. Dua operator di dua HP adalah keadaan sehari-hari.
    """
    import asyncio

    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=100)

    async def coba():
        async with pg() as db:
            try:
                h = await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                                        rec_id=r.rec.id)
                return f"menang: {h.rec.kode}"
            except bk.BarangKeluarError as e:
                return f"tolak: {e}"

    hasil = await asyncio.gather(coba(), coba())
    menang = [x for x in hasil if x.startswith("menang")]
    tolak = [x for x in hasil if x.startswith("tolak")]
    assert len(menang) == 1 and len(tolak) == 1, hasil
    # Kalimatnya menyebut orangnya, bukan teks Postgres.
    assert "Op Polesan" in tolak[0], tolak[0]
    assert "IntegrityError" not in tolak[0] and "psycopg" not in tolak[0].lower()
    # Dan stoknya berkurang SEKALI.
    assert await _stok(pg, gudang) == 7_500, "muatan terhitung dua kali"


async def test_perintah_yang_dibatalkan_mengembalikan_stok_yang_bisa_keluar(pg, gudang):
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=300)
    async with pg() as db:
        await bk.batalkan(db, user=await db.get(User, gudang["adm"]),
                          rec_id=r.rec.id, sebab="Pembeli membatalkan")
    # Yang tadinya ditolak kini boleh — pesanannya tak lagi menahan stok.
    r2 = await _perintah(pg, gudang, karung=300, pembeli="Toko Lain")
    assert r2.rec.kode != r.rec.kode


async def test_batal_menuntut_sebab(pg, gudang):
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.batalkan(db, user=await db.get(User, gudang["adm"]),
                              rec_id=r.rec.id, sebab="  ")
    assert "sebab" in str(e.value).lower()


# ──────────────────────── Taut tiket timbang keluar ────────────────────────
#
# ⚠ URUTAN WAKTUNYA TERBALIK DARI SISI MASUK, dan itu yang membentuk seluruh
# bagian ini: truk masuk KOSONG, dimuat, lalu ditimbang bermuatan saat keluar.
# Tiketnya baru lengkap SESUDAH barangnya naik — jadi ia ditempel di langkah
# verifikasi, dan tak boleh jadi syarat di langkah mana pun sebelumnya.

from sqlalchemy import text as _text                                  # noqa: E402

_SQL_TIKET_KELUAR = _text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_barang_kg, berat_acuan_kg, status_tiket, status_transaksi)
    VALUES
        (:kode, :tanggal, :arah, 'BERAS', 'DUA_KALI', :pembeli,
         'B 1234 XY', 5000, :waktu, :netto, :barang, 0, 'SELESAI', :st)
    RETURNING id
""")


async def _tiket(pg, kode, *, arah="KELUAR", barang=2_480, st="AKTIF",
                 pembeli="Toko Makmur", tanggal=None):
    from datetime import datetime, timezone

    from app.database import now_local
    async with pg() as db:
        tid = (await db.execute(_SQL_TIKET_KELUAR, {
            "kode": kode, "tanggal": tanggal or now_local().date(), "arah": arah,
            "waktu": datetime.now(timezone.utc), "netto": barang + 20,
            "barang": barang, "st": st, "pembeli": pembeli})).scalar_one()
        await db.commit()
        return tid


async def _sampai_dimuat(pg, g, karung=100, pembeli="Toko Makmur"):
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, g, karung=karung, pembeli=pembeli)
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, g["op"]), rec_id=r.rec.id)
    return r.rec.id


async def test_verifikasi_menyebut_selisih_timbangan(pg, gudang):
    """Beda bobot TIDAK menolak apa pun — muatan sungguhan memang berselisih:
    karung tak persis 25,0 kg, dan truk membawa terpal. Yang dikerjakan cuma
    MENYEBUTKAN selisihnya, dan satu kalimat itulah yang membuat tautan ini
    berguna alih-alih sekadar ada."""
    from app.models import User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=100)      # 2.500 kg
    tid = await _tiket(pg, "TK-001", barang=2_480)
    async with pg() as db:
        rec, catatan = await bk.verifikasi(
            db, user=await db.get(User, gudang["adm"]), rec_id=rid,
            timbangan_transaksi_id=tid)
    assert rec.timbangan_transaksi_id == tid
    assert "2.480" in catatan and "2.500" in catatan and "20" in catatan, catatan


async def test_satu_tiket_tak_boleh_dipakai_dua_transaksi(pg, gudang):
    """Indeks PARSIAL yang menjaganya, bukan pemeriksaan di depan.

    Dan penolakannya harus berkalimat manusia: yang sampai ke Admin tak boleh
    berupa teks Postgres tentang indeks unik.
    """
    from app.models import User
    from app.services import barang_keluar as bk

    # Kedua muatan sama besarnya, dan tiketnya sepadan dengan keduanya:
    # sejak 30 September 2026 selisih timbang yang BESAR menuntut sebab, dan
    # pagar itu berdiri sebelum penautan tiket sempat diuji. Yang dipersoalkan
    # uji ini keunikan tiketnya, bukan bobotnya.
    tid = await _tiket(pg, "TK-002", barang=2_500)
    a = await _sampai_dimuat(pg, gudang, karung=100)
    b = await _sampai_dimuat(pg, gudang, karung=100)
    async with pg() as db:
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=a, timbangan_transaksi_id=tid)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                                rec_id=b, timbangan_transaksi_id=tid)
    pesan = str(e.value)
    assert "sudah tertaut" in pesan, pesan
    assert "UniqueViolation" not in pesan and "psycopg" not in pesan.lower()


async def test_tiket_arah_masuk_ditolak(pg, gudang):
    """Daftar yang ditawarkan layar memang sudah menyaring — tetapi rutenya bisa
    dipanggil dengan id apa pun, dan tiket MASUK yang tertempel di barang keluar
    akan membuat satu truk gabah terhitung sebagai penjualan beras."""
    from app.models import User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang)
    tid = await _tiket(pg, "TK-003", arah="MASUK")
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                                rec_id=rid, timbangan_transaksi_id=tid)
    assert "MASUK" in str(e.value)


async def test_tiket_yang_dibatalkan_di_pos_timbang_ditolak(pg, gudang):
    """Tiket yang DIBATALKAN atau DITUTUP PAKSA pernah tetap mendorong 9.800 kg
    ke pembukuan lewat sisi masuk (temuan QA T-02). Syaratnya dipakai ulang di
    sini, bukan ditulis ulang."""
    from app.models import User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang)
    tid = await _tiket(pg, "TK-004", st="BATAL")
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                                rec_id=rid, timbangan_transaksi_id=tid)
    assert "dibatalkan" in str(e.value).lower()


async def test_daftar_tiket_keluar_menyembunyikan_yang_sudah_tertaut(pg, gudang):
    """Dan MEMUNCULKANNYA LAGI bila transaksinya dibatalkan — itu yang dijaga
    indeks parsial `WHERE status <> 'batal'`. Tiket yang terkunci selamanya
    membuat truk yang salah dicatat tak punya jalan pulang."""
    from sqlalchemy import update

    from app.models import OutgoingRecord, User
    from app.penggilingan.gudang1.services.timbang_link import tiket_keluar_aktif
    from app.penggilingan.inventory.models import OUT_BATAL
    from app.services import barang_keluar as bk

    tid = await _tiket(pg, "TK-005")
    rid = await _sampai_dimuat(pg, gudang)
    async with pg() as db:
        assert tid in {t["id"] for t in await tiket_keluar_aktif(db)}
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=rid, timbangan_transaksi_id=tid)
    async with pg() as db:
        assert tid not in {t["id"] for t in await tiket_keluar_aktif(db)}, \
            "tiket yang sudah tertaut masih ditawarkan"
        # Transaksinya dibatalkan (mis. koreksi) → tiketnya bebas lagi.
        await db.execute(update(OutgoingRecord)
                         .where(OutgoingRecord.id == rid)
                         .values(status=OUT_BATAL))
        await db.commit()
    async with pg() as db:
        assert tid in {t["id"] for t in await tiket_keluar_aktif(db)}, \
            "tiket terkunci selamanya sesudah transaksinya dibatalkan"


async def test_tiket_tak_ditawarkan_untuk_muatan_kecil(pg, gudang):
    """⭐ Keputusan pemilik 5 Oktober 2026: muatan < 200 kg tak lagi
    menawarkan medan "Kode timbang keluar" — `/actions/timbang-keluar-aktif
    ?induk=<rec_id>` menjawab daftar KOSONG untuk muatan sekecil ini,
    walau ada tiket yang sungguh menganggur."""
    from app.models import User
    from app.web.aksi_inventory import timbang_keluar_aktif

    await _tiket(pg, "TK-KECIL-01")
    rid = await _sampai_dimuat(pg, gudang, karung=5)          # 125 kg
    async with pg() as db:
        out = await timbang_keluar_aktif(induk=str(rid), user=await db.get(User, gudang["adm"]))
    assert out == []


async def test_tiket_tetap_ditawarkan_untuk_muatan_besar(pg, gudang):
    """Ambangnya 200 kg, bukan nol — muatan yang memang besar tetap
    menawarkan tiketnya seperti biasa."""
    from app.models import User
    from app.web.aksi_inventory import timbang_keluar_aktif

    tid = await _tiket(pg, "TK-BESAR-01")
    rid = await _sampai_dimuat(pg, gudang, karung=10)          # 250 kg
    async with pg() as db:
        out = await timbang_keluar_aktif(induk=str(rid), user=await db.get(User, gudang["adm"]))
    assert tid in {int(o["value"]) for o in out}


async def test_picker_verifikasi_tiket_hanya_difilter_berdasarkan_nama(pg, gudang):
    """Nama pembeli saja yang menyaring tiket; tanggal dan bobot berbeda
    tidak menghilangkan tiket yang mungkin memang untuk truk tersebut."""
    from app.models import User
    from app.web.aksi_inventory import timbang_keluar_aktif

    cocok = await _tiket(pg, "TK-NAMA-COCOK", barang=9_000,
                         pembeli="  TOKO   MAKMUR  ")
    await _tiket(pg, "TK-NAMA-LAIN", pembeli="Toko Sejahtera")
    rid = await _sampai_dimuat(pg, gudang, karung=10, pembeli="Toko Makmur")
    async with pg() as db:
        out = await timbang_keluar_aktif(
            induk=str(rid), user=await db.get(User, gudang["adm"]))
    assert {int(o["value"]) for o in out} == {cocok}


async def test_tiket_tanpa_induk_atau_induk_tak_dikenal_tetap_daftar_penuh(pg, gudang):
    """Borang yang dibuka lewat katalog (bukan lewat kartu per-muatan) belum
    punya `induk` sama sekali saat medan ini pertama kali termuat — dan
    `induk` yang tak dikenal (id usang, borang basi) tak boleh diam-diam
    menyembunyikan tiket yang sungguh ada. Hanya muatan yang BENAR
    DITEMUKAN dan BENAR kecil yang menyembunyikannya."""
    from app.models import User
    from app.web.aksi_inventory import timbang_keluar_aktif

    tid = await _tiket(pg, "TK-TANPA-INDUK-01")
    await _sampai_dimuat(pg, gudang, karung=5)                # ada muatan kecil, tak dipakai
    async with pg() as db:
        admin = await db.get(User, gudang["adm"])
        kosong = await timbang_keluar_aktif(induk="", user=admin)
        asing = await timbang_keluar_aktif(induk="999999", user=admin)
    assert tid in {int(o["value"]) for o in kosong}
    assert tid in {int(o["value"]) for o in asing}


async def test_tiket_tetap_bisa_ditautkan_ke_muatan_kecil_bukan_larangan(pg, gudang):
    """⚠ TAK DITAWARKAN ≠ TAK DIIZINKAN. Kalau muatan sekecil ini kebetulan
    ditimbang, tiketnya tetap tertaut seperti muatan besar manapun — yang
    berubah cuma apakah app MENAWARKAN."""
    from app.models import User
    from app.services import barang_keluar as bk

    tid = await _tiket(pg, "TK-KECIL-DIPAKAI-01", barang=125)
    rid = await _sampai_dimuat(pg, gudang, karung=5)           # 125 kg
    async with pg() as db:
        rec, _ = await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                                     rec_id=rid, timbangan_transaksi_id=tid)
    assert rec.timbangan_transaksi_id == tid


async def test_pilihan_armada_bergantung_perintah_dan_js_memicu_perubahannya():
    """Armada dipilih sekali pada perintah; verifikasi tidak memilih ulang."""
    import pathlib
    from app.web.aksi_inventory import spesifikasi
    aksi = next(x for x in spesifikasi(g2=True, fin=True) if x['id'] == 'pilih_tiket_armada')
    medan = next(x for x in aksi['fields'] if x['name'] == 'tiket_armada')
    assert medan['induk'] == 'perintah'
    js = (pathlib.Path(__file__).resolve().parents[2]
          / 'hmu_tampilan/static/aksi.js').read_text()
    j = js.index('function isiDariBaris')
    assert 'dispatchEvent(new Event("change"' in js[j:j + 1200]


async def test_verifikasi_boleh_tanpa_tiket(pg, gudang):
    """Tiket bisa belum ada — truk yang keluar lewat pintu belakang, atau
    timbangan yang sedang rusak. Menolak penutupan karenanya akan membuat
    muatan menggantung di meja Admin sampai tiketnya muncul, dan angka stok
    yang benar tertahan oleh kertas."""
    from app.models import User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang)
    async with pg() as db:
        rec, catatan = await bk.verifikasi(
            db, user=await db.get(User, gudang["adm"]), rec_id=rid)
    assert rec.status == "selesai" and catatan == ""


async def test_pk_mentah_keluar_dan_mengurangi_stok_pk(pg, gudang):
    """Keputusan pemilik 29 September 2026, meluruskan salah tangkap sehari
    sebelumnya: "pk juga bisa dijual dan mengurangi stock pk. tetapi istilah
    dijual kan harus tau harganya. sedangkan sistem produksi tidak boleh ada
    sangkut paut dengan harga."

    Jadi yang dikeluarkan dari Pos Produksi HARGANYA, bukan barangnya. PK yang
    naik truk memang berkurang dari stok Gudang 1 — gudang yang stoknya tak
    pernah berkurang akan menawarkan PK yang sudah lama pergi, dan lot yang
    ditawarkan lalu tak ada barangnya membuat operator berhenti mempercayai
    daftarnya.
    """
    from app.database import now_local
    from app.models import MillingProcess, MillingProgressLog, User
    from app.services import barang_keluar as bk
    from app.services.transfer import pending_transfer_kg

    async with pg() as db:
        proc = MillingProcess(kode_proses="LOT-KLR-01", status="selesai",
                              silo_id=gudang["silo"],
                              berat_gabah_masuk_kg=10_000, waktu_mulai=now_local(),
                              waktu_selesai=now_local(), created_by=gudang["op"])
        db.add(proc)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=proc.id,
                                  berat_kumulatif_kg=6_000,
                                  waktu_update=now_local(), input_by=gudang["op"]))
        await db.commit()
        pid = proc.id
        awal = float(await pending_transfer_kg(db, pid))
    assert awal == 6_000, awal

    klien = await _pelanggan(pg, "Pabrik Seberang")
    async with pg() as db:
        r = await bk.buat_perintah(
            db, user=await db.get(User, gudang["adm"]),
            baris=[bk.BarisPerintah(tipe="pk_langsung", milling_process_id=pid,
                                    berat_kg=2_000)],
            pelanggan_id=klien)
    async with pg() as db:
        # Perintah BELUM memindahkan apa pun — PK-nya masih di Gudang 1.
        assert float(await pending_transfer_kg(db, pid)) == 6_000

    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                            rec_id=r.rec.id)
    async with pg() as db:
        assert float(await pending_transfer_kg(db, pid)) == 4_000, \
            "stok PK tak berkurang saat PK keluar pabrik"


async def test_perintah_pk_melebihi_sisa_lot_ditolak_dengan_angkanya(pg, gudang):
    from app.database import now_local
    from app.models import MillingProcess, MillingProgressLog, User
    from app.services import barang_keluar as bk

    klien = await _pelanggan(pg, "Pabrik Seberang")
    async with pg() as db:
        proc = MillingProcess(kode_proses="LOT-KLR-02", status="selesai",
                              silo_id=gudang["silo"],
                              berat_gabah_masuk_kg=5_000, waktu_mulai=now_local(),
                              waktu_selesai=now_local(), created_by=gudang["op"])
        db.add(proc)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=proc.id,
                                  berat_kumulatif_kg=3_000,
                                  waktu_update=now_local(), input_by=gudang["op"]))
        await db.commit()
        pid = proc.id
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.buat_perintah(
                db, user=await db.get(User, gudang["adm"]),
                baris=[bk.BarisPerintah(tipe="pk_langsung",
                                        milling_process_id=pid, berat_kg=4_000)],
                pelanggan_id=klien)
    assert "3.000" in str(e.value), str(e.value)


async def test_tak_satu_pun_langkah_rantai_menyimpan_rupiah(pg, gudang):
    """Keputusan pemilik: "termasuk beras yang keluar. tidak boleh melampirkan
    harga."

    Diuji pada BARIS YANG TERSIMPAN, bukan pada borangnya: borang yang bersih
    tak menolong bila layanannya diam-diam mengisi kolomnya dari tempat lain.
    """
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=40)
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                            rec_id=r.rec.id)
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=r.rec.id)
    async with pg() as db:
        rec, items = (await bk.daftar(db))[0]
    for it in items:
        assert it.harga_per_kg is None, "baris keluar menyimpan harga"
        assert it.total_harga is None, "baris keluar menyimpan total rupiah"


async def test_satu_borang_menerima_beberapa_item_sekaligus(pg, gudang):
    """Permintaan pemilik 29 September 2026: "admin bisa memilih barang yang akan
    keluar beserta jumlahnya. lalu bisa klik tambah item lalu keluar field baru
    untuk memilih item lain beserta jumlahnya, karena barang keluar bisa multi
    item."

    Diuji lewat RUTENYA, dengan muatan yang benar-benar dikirim medan
    `ulang_barang` — daftar {pilih, jumlah}. Menguji layanannya saja tak
    menyentuh bagian yang paling mudah salah: mengurai pasangan, dan memilah
    SATUAN dari awalan nilainya.
    """
    from app.database import now_local
    from app.models import MillingProcess, MillingProgressLog, User
    from app.web import aksi_inventory as inv

    async with pg() as db:
        proc = MillingProcess(kode_proses="LOT-MULTI-01", status="selesai",
                              silo_id=gudang["silo"], berat_gabah_masuk_kg=9_000,
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=gudang["op"])
        db.add(proc)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=proc.id,
                                  berat_kumulatif_kg=5_000,
                                  waktu_update=now_local(), input_by=gudang["op"]))
        await db.commit()

    klien = await _pelanggan(pg, "Toko Makmur")
    async with pg() as db:
        u = await db.get(User, gudang["adm"])
        r = await inv.act_perintah_keluar(inv.PerintahKeluarReq(
            barang=[
                inv.BarisReq(pilih=f"bj:{gudang['sku']}|{gudang['std']}", jumlah=100),
                inv.BarisReq(pilih="pk:LOT-MULTI-01", jumlah=1_500),
            ],
            pelanggan=str(klien), no_polisi="B 1234 XY"), user=u)
    assert r["ok"], r

    from app.services import barang_keluar as bk
    async with pg() as db:
        rec, items = (await bk.daftar(db))[0]
    assert r["tujuan"] == f"/barang-keluar/{rec.id}"
    assert len(items) == 2, "kedua item tak masuk satu transaksi"
    jenis = {i.item_type for i in items}
    assert jenis == {"finished_goods", "pk_langsung"}, jenis
    # ── SATUANNYA dipilah dari AWALAN nilainya ──
    # `bj:` per karung (100 × 25 kg), `pk:` per kilogram apa adanya. Tanpa
    # awalan, "100" di satu baris berarti 100 karung dan di baris lain 100 kg,
    # dan yang membedakan cuma ingatan orang yang mengetiknya.
    bj = next(i for i in items if i.item_type == "finished_goods")
    pk = next(i for i in items if i.item_type == "pk_langsung")
    assert float(bj.berat_perintah_kg) == 2_500, float(bj.berat_perintah_kg)
    assert bj.jumlah_karung_perintah == 100
    assert float(pk.berat_perintah_kg) == 1_500, float(pk.berat_perintah_kg)


async def test_baris_terisi_separuh_ditolak_dengan_menyebut_barangnya(pg, gudang):
    """Layar sudah membuang baris yang KOSONG SELURUHNYA. Yang terisi separuh
    sampai ke sini — dan ia ditolak, bukan dibuang diam-diam: perintah yang
    kurang satu barang tanpa sebab akan ditemukan operator di depan truk."""
    from app.models import User
    from app.web import aksi_inventory as inv
    from fastapi import HTTPException

    klien = await _pelanggan(pg, "Toko Makmur")
    async with pg() as db:
        u = await db.get(User, gudang["adm"])
        with pytest.raises(HTTPException) as e:
            await inv.act_perintah_keluar(inv.PerintahKeluarReq(
                barang=[
                    inv.BarisReq(pilih=f"bj:{gudang['sku']}|{gudang['std']}", jumlah=40),
                    inv.BarisReq(pilih=f"bj:{gudang['sku']}|{gudang['std']}"),
                ],
                pelanggan=str(klien)), user=u)
    assert "jumlah" in str(e.value.detail).lower(), e.value.detail


async def test_bentuk_borang_lama_masih_diterima(pg, gudang):
    """Lembar yang sudah terbuka di layar orang saat versi baru terbit masih
    mengirim bentuk lama — satu barang, `stok` + `jumlah_karung`. Halaman di
    ponsel berumur panjang; yang berhenti cuma MENAWARKANNYA."""
    from app.models import User
    from app.web import aksi_inventory as inv

    klien = await _pelanggan(pg, "Toko Lama")
    async with pg() as db:
        u = await db.get(User, gudang["adm"])
        r = await inv.act_perintah_keluar(inv.PerintahKeluarReq(
            stok=f"{gudang['sku']}|{gudang['std']}", jumlah_karung=20,
            pelanggan=str(klien)), user=u)
    assert r["ok"], r


async def test_halaman_barang_keluar_menyusun_menurut_TRUK(pg, gudang):
    """Permintaan pemilik 28 September 2026: "kita butuh satu halaman untuk
    transaksi barang keluar."

    Sampai halaman ini ada, catatan barang keluar tersebar di kartu Stok Produk
    (per KATEGORI) dan di List audit (baris mentah). Keduanya menyusun menurut
    BARANG, jadi tak satu pun bisa menjawab pertanyaan yang sebenarnya
    ditanyakan orang: "truk yang tadi siang bawa apa saja?"

    Yang dijaga di sini: satu kartu per TRANSAKSI, isinya seluruh macam
    barangnya, keadaannya terbaca, dan yang belum selesai berdiri paling atas.
    """
    import httpx
    from sqlalchemy import select

    from app.database import now_local
    from app.models import ProduksiAkun, User
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.penggilingan.inventory.finished_goods import catat_bekatul
    from app.services import barang_keluar as bk
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    from app.main import app

    # Satu transaksi SELESAI, satu masih menunggu dimuat.
    lama = await _perintah(pg, gudang, karung=40, pembeli="Toko Lama")
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                            rec_id=lama.rec.id)
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=lama.rec.id)
    baru = await _perintah(pg, gudang, karung=100, pembeli="Toko Baru")
    # Barang KEDUA yang benar-benar berbeda — sejak 29 September 2026 barang
    # yang sama DIGABUNG ke barisnya, jadi menambah beras yang sama lagi tetap
    # menghasilkan "1 macam" dan uji ini takkan menguji apa pun.
    async with pg() as db:
        proc = (await db.execute(select(PolishingProcess))).scalars().first()
        db.add(PolishingOutputLog(polishing_process_id=proc.id, jenis="bekatul",
                                  berat_kg=1_000, waktu_update=now_local(),
                                  input_by=gudang["op"]))
        await db.commit()
        await catat_bekatul(db, user=await db.get(User, gudang["op"]),
                            kode_pol=proc.kode_proses, berat_kg=1_000)
        await bk.tambah_baris(
            db, user=await db.get(User, gudang["adm"]), rec_id=baru.rec.id,
            baris=bk.BarisPerintah(tipe="byproduct_curah", jenis="bekatul",
                                   berat_kg=300))
        a = ProduksiAkun(user_id=gudang["adm"], username="uji_halaman_keluar",
                         password_hash=S.hash_sandi("rahasia123"), status="aktif",
                         mode_perangkat=mode_bawaan("admin"))
        db.add(a)
        await db.commit()
        token = security.buat_token(a)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://uji") as c:
        c.cookies.set(security.NAMA_COOKIE, token)
        c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
        r = await c.get("/barang-keluar")
    assert r.status_code == 200, r.text[:400]
    h = r.text

    # Kedua transaksi berkartu, dengan kodenya.
    assert lama.rec.kode in h and baru.rec.kode in h
    # Yang BELUM selesai berdiri lebih atas — yang membuka halaman ini di
    # tengah hari mencari muatan yang sedang berjalan, bukan riwayat kemarin.
    assert h.index(baru.rec.kode) < h.index(lama.rec.kode), \
        "riwayat mendorong muatan yang sedang berjalan ke bawah layar"
    # Keadaannya terbaca sebagai kata, bukan kode.
    assert "Menunggu dimuat" in h and "Selesai" in h
    # Satu kartu memuat KEDUA macam barangnya — itu seluruh sebab halaman ini.
    assert "2 macam" in h, "isi muatan tak disebut per transaksi"
    assert "Beras Medium" in h
    # Pembeli & truknya ikut: yang mencari truk tertentu mencarinya lewat plat.
    assert "Toko Baru" in h and "B 1234 XY" in h
    # Dan jejak tiga langkahnya terbaca pada yang sudah tutup — SIAPA, bukan
    # cuma KAPAN (permintaan pemilik 7 Oktober 2026: "diperintah siapa,
    # dimuat siapa, dan diverifikasi siapa harus jelas"). `lama` lewat
    # ketiga langkah: `_perintah`/`verifikasi` oleh "Admin Uji", `muat_semua`
    # oleh "Op Polesan" — dan NAMANYA, bukan cuma labelnya, wajib tergambar.
    # Riwayat diringkas menjadi tabel; jejak lengkap ada di halaman detail
    # yang dituju tautannya. Tetap uji nama ketiga pelaku melalui HTTP.
    assert f'href="/barang-keluar/{lama.rec.id}"' in h
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://uji") as c:
        c.cookies.set(security.NAMA_COOKIE, token)
        detail = await c.get(f"/barang-keluar/{lama.rec.id}")
    assert detail.status_code == 200
    h = detail.text
    assert "Diperintah" in h and "Dimuat" in h and "Diverifikasi" in h
    assert h.count("Admin Uji") >= 2, \
        "nama pemerintah & pemverifikasi tak tergambar di jejaknya"
    assert "Op Polesan" in h, "nama pemuat tak tergambar di jejaknya"


async def test_operator_selepan_tak_ditawari_pintu_barang_keluar(pg, gudang):
    """Pintu Barang Keluar diputuskan `pintu_produk` — syarat yang SAMA yang
    dulu juga menentukan nasib pintu Stok Produk sendiri.

    ⚠ TAK LAGI DIBANDINGKAN LANGSUNG sejak 5 Oktober 2026: "Stok Produk"
    diserap sub-menu "Stok" dan pintunya sendiri kini SELALU padam, apa pun
    `pintu_produk`-nya (lihat `tests/test_grup_antrean.py::
    test_pintu_stok_produk_sendiri_selalu_padam_di_laci`) — jadi
    membandingkan keduanya di sini akan gagal persis pada skenario uji ini
    (`pintu_produk` True, tempat "barang_keluar" tetap hidup tapi
    "stok_produk" tetap mati). Yang diperiksa sekarang `barang_keluar`
    SAJA; sisi "Stok Produk" sudah dijaga ujinya sendiri.
    """
    from app.models import User
    from app.services.berjalan import untuk

    async with pg() as db:
        u = await db.get(User, gudang["op"])
        u.default_warehouse_id = None          # bukan operator Gudang 2
        await db.commit()
        b = await untuk(db, u)
    assert "barang_keluar" not in b.lencana()["PINTU_MATI"], \
        "operator yang bukan G1 pun kehilangan Barang Keluar"


# ──────────────────────── Kartu: pekerjaan yang MENCARI orangnya ────────────

async def test_operator_gudang2_melihat_perintah_muat_sebagai_kartu(pg, gudang):
    """Sampai 29 September 2026 rantai ini berjalan LEWAT KATALOG AKSI saja.

    Operator harus membuka menu dan memilih "Muat semua sesuai perintah", jadi
    perintah yang terbit pukul tujuh pagi baru dilihat pukul sebelas. Di seluruh
    app ini pekerjaan muncul SENDIRI sebagai kartu; barang keluar satu-satunya
    yang tidak — dan pekerjaan yang harus dicari adalah pekerjaan yang terlambat.
    """
    from app.services.berjalan import untuk_operator_gudang2

    r = await _perintah(pg, gudang, karung=100, pembeli="Toko Makmur")
    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    k = next((x for x in b.menunggu if x.kode == r.rec.kode), None)
    assert k is not None, "perintah muat tak berkartu di antrean operator"
    assert "Toko Makmur" in k.isi and "B 1234 XY" in k.isi, k.isi
    # Fase SENDIRI, bukan pinjaman. Kartu berjudul "Muat barang keluar" yang
    # berkeping "PROSES SOSOH" sudah jadi cacat yang sama tiga kali sebelumnya.
    assert k.fase == "keluar", k.fase
    from app.services.berjalan import grup_baris
    assert grup_baris(k) == "muat"
    assert b.jumlah_grup()["muat"] == 1
    # Tiga pilihan, dan "muat semua" paling atas — keadaan yang paling sering.
    aksi = [p[0] for p in (k.pilihan or [])]
    assert aksi[:1] == ["muat_semua"], aksi
    assert {"muat_barang", "selesai_muat"} <= set(aksi), aksi


async def test_kartu_muat_mendarat_di_gudang_yang_memegang_barangnya(pg, gudang):
    """Perintah berisi PK MENTAH mendarat di Gudang 1; yang berisi barang jadi
    saja tak pernah sampai ke sana.

    Dihitung dari BARANGNYA, bukan dipilih Admin — perintah yang mendarat di
    layar yang salah akan berdiri di sana sampai seseorang menelepon.
    """
    from app.database import now_local
    from app.models import MillingProcess, MillingProgressLog, User
    from app.services import barang_keluar as bk
    from app.services.berjalan import untuk_gudang1, untuk_operator_gudang2

    # Perintah A: barang jadi saja.
    a = await _perintah(pg, gudang, karung=40, pembeli="Toko A")
    # Perintah B: PK mentah.
    klien = await _pelanggan(pg, "Pabrik Seberang")
    async with pg() as db:
        proc = MillingProcess(kode_proses="LOT-KARTU-01", status="selesai",
                              silo_id=gudang["silo"], berat_gabah_masuk_kg=8_000,
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=gudang["op"])
        db.add(proc)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=proc.id,
                                  berat_kumulatif_kg=4_000,
                                  waktu_update=now_local(), input_by=gudang["op"]))
        await db.commit()
        bb = await bk.buat_perintah(
            db, user=await db.get(User, gudang["adm"]),
            baris=[bk.BarisPerintah(tipe="pk_langsung",
                                    milling_process_id=proc.id, berat_kg=1_000)],
            pelanggan_id=klien)

    async with pg() as db:
        g1 = await untuk_gudang1(db)
        g2 = await untuk_operator_gudang2(db)
    kode_g1 = {x.kode for x in g1.menunggu}
    kode_g2 = {x.kode for x in g2.menunggu}
    assert bb.rec.kode in kode_g1, "perintah PK tak sampai ke Gudang 1"
    assert a.rec.kode not in kode_g1, "perintah barang jadi bocor ke Gudang 1"
    assert a.rec.kode in kode_g2, "perintah barang jadi tak sampai ke Gudang 2"


async def test_verifikasi_pengiriman_cukup_di_barang_keluar(pg, gudang):
    """Verifikasi pengiriman tidak digandakan ke Menunggu Keputusan."""
    from app.models import User
    from app.services import barang_keluar as bk
    from app.services.berjalan import untuk_staff

    r = await _perintah(pg, gudang, karung=100)
    baris = r.baris[0]
    async with pg() as db:
        await bk.catat_muatan(db, user=await db.get(User, gudang["op"]),
                              item_id=baris.id, jumlah_karung=80)
        await bk.selesai_muat(db, user=await db.get(User, gudang["op"]),
                              rec_id=r.rec.id, sebab="Truk penuh; sisa tidak terkirim")
    async with pg() as db:
        b = await untuk_staff(db)
    assert r.rec.kode not in {x.kode for x in b.meja}
    assert "verifikasi_keluar" not in b.jumlah_grup_keputusan()
    c = await _klien(pg, gudang["adm"], "uji_verifikasi_satu_pintu")
    async with c:
        h = (await c.get(f"/barang-keluar/{r.rec.id}")).text
    assert r.rec.kode in h
    assert "buka=verifikasi_keluar" in h
    assert "500" in h and "Sisa perintah" in h


async def test_kartu_tiket_keluar_menganggur_tetap_benar_walau_ditahan(pg, gudang):
    """Cerminan kartu "Tiket timbang belum dicatat" di sisi masuk.

    Tanpa ini, tiket keluar yang terlewat menghilang diam-diam: ia ditimbang di
    Pos Timbang lalu berhenti di situ, dan tak ada satu pun layar Produksi yang
    menyebutnya.

    DIAM — tanpa tombol. Jalan menautkannya lewat kartu verifikasi muatannya;
    menautkan tiket ke transaksi yang BELUM ada berarti mengarang muatannya.

    ⚠ DITAHAN dari `untuk_staff()` sejak 6 Oktober 2026 (keputusan pemilik:
    kartunya belum punya tindak lanjut yang berguna) — lihat komentar di
    pemanggilnya yang dulu, `untuk_staff()`. Fungsinya SENDIRI tetap ada dan
    tetap diuji LANGSUNG di sini, supaya tinggal disambung lagi begitu ada
    tindak lanjutnya; uji inilah yang menjaganya tak diam-diam rusak selama
    ditahan.
    """
    from datetime import timedelta

    from app.database import now_local
    from app.services import berjalan as svc
    from sqlalchemy import text as _t

    tid = await _tiket(pg, "TK-LEWAT-01")
    async with pg() as db:
        # Dimundurkan sehari: tiket HARI INI wajar belum tertaut — truknya baru
        # keluar dan Admin belum sampai ke mejanya. Kartu yang menagih
        # pekerjaan yang belum waktunya akan diabaikan bersama yang sungguhan.
        await db.execute(_t("UPDATE timbangan_transaksi SET tanggal = :t "
                            "WHERE id = :id"),
                         {"t": now_local().date() - timedelta(days=1), "id": tid})
        await db.commit()

    async with pg() as db:
        kartu = await svc._kartu_tiket_keluar_menganggur(db)
    k = next((x for x in kartu if x.kode == "TK-LEWAT-01"), None)
    assert k is not None, "tiket keluar yang terlewat tak berkartu"
    assert k.aksi is None, "kartunya bertombol — ia seharusnya DIAM"
    assert k.fase == "keluar", k.fase
    assert "Pos Timbang" in (k.nota or ""), k.nota

    async with pg() as db:
        b = await svc.untuk_staff(db)
    assert "TK-LEWAT-01" not in {x.kode for x in b.meja}, \
        "ditahan dari tampilan tapi masih muncul di Menunggu keputusan"


async def test_tiket_keluar_hari_ini_belum_ditagih(pg, gudang):
    """Sisi lain, dan ia wajib ada: kartu yang muncul terlalu cepat menagih
    pekerjaan yang belum waktunya, dan yang ditagih terlalu sering berhenti
    dibaca."""
    from app.services.berjalan import untuk_staff

    await _tiket(pg, "TK-HARI-INI")
    async with pg() as db:
        b = await untuk_staff(db)
    assert "TK-HARI-INI" not in {x.kode for x in b.meja}


async def test_tiket_yang_sudah_tertaut_berhenti_ditagih(pg, gudang):
    """`_kartu_tiket_keluar_menganggur` diuji LANGSUNG (bukan lewat
    `untuk_staff()`, yang sejak 6 Oktober 2026 tak lagi memanggilnya — lihat
    `test_kartu_tiket_keluar_menganggur_tetap_benar_walau_ditahan`): yang
    diperiksa di sini murni `tiket_keluar_aktif()` berhenti menyebut tiket
    begitu ia tertaut, dan itu tak bergantung pada apakah kartunya sedang
    ditampilkan atau tidak.
    """
    from datetime import timedelta

    from app.database import now_local
    from app.models import User
    from app.services import barang_keluar as bk
    from app.services.berjalan import _kartu_tiket_keluar_menganggur
    from sqlalchemy import text as _t

    # Bobot tiketnya sepadan dengan muatan 40 karung × 25 kg — lihat alasan
    # di `test_satu_tiket_tak_boleh_dipakai_dua_transaksi`.
    tid = await _tiket(pg, "TK-TAUT-01", barang=1_000)
    async with pg() as db:
        await db.execute(_t("UPDATE timbangan_transaksi SET tanggal = :t "
                            "WHERE id = :id"),
                         {"t": now_local().date() - timedelta(days=1), "id": tid})
        await db.commit()
    rid = await _sampai_dimuat(pg, gudang, karung=40)
    async with pg() as db:
        kartu = await _kartu_tiket_keluar_menganggur(db)
    assert "TK-TAUT-01" in {x.kode for x in kartu}, "belum tertaut, harus ditagih"

    async with pg() as db:
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=rid, timbangan_transaksi_id=tid)
    async with pg() as db:
        kartu = await _kartu_tiket_keluar_menganggur(db)
    assert "TK-TAUT-01" not in {x.kode for x in kartu}, \
        "tiket yang sudah tertaut masih ditagih"


# ──────────── Pintu masuknya di HALAMANNYA, bukan di katalog ────────────

async def _klien(pg, uid, nama, mode="admin"):
    import httpx

    from app.models import ProduksiAkun
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    from app.main import app

    async with pg() as db:
        a = ProduksiAkun(user_id=uid, username=nama,
                         password_hash=S.hash_sandi("rahasia123"), status="aktif",
                         mode_perangkat=mode_bawaan(mode))
        db.add(a)
        await db.commit()
        token = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji")
    c.cookies.set(security.NAMA_COOKIE, token)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    return c


async def test_tombol_perintah_ada_di_halaman_barang_keluar(pg, gudang):
    """Permintaan pemilik 29 September 2026: "saya tidak suka proses barang
    keluar prosesnya dilakukan di catat pekerjaan lain. buat tombol di barang
    keluar yaitu perintah barang keluar ... lalu hapus tombol yang ada di catat
    pekerjaan lain."

    Tombolnya membuka LEMBAR AKSI YANG SAMA (`/aksi?buka=…`), bukan borang
    kedua: dua borang untuk satu pekerjaan akan berselisih isinya pada
    perubahan berikutnya.
    """
    await _perintah(pg, gudang, karung=40)
    c = await _klien(pg, gudang["adm"], "uji_tombol_admin")
    async with c:
        r = await c.get("/barang-keluar")
    assert r.status_code == 200, r.status_code
    h = r.text
    # ⚠ ALAMATNYA BERUBAH 29 September 2026: tombolnya dulu menunjuk
    # `/aksi?buka=…` dan memindahkan orang ke Antrian tunggu. Sekarang ia
    # membuka lembarnya DI HALAMAN INI — lihat
    # `test_tombolnya_membuka_lembar_di_halaman_ini`.
    assert "/barang-keluar?buka=perintah_keluar" in h, \
        "tombol perintah tak ada di halamannya"
    # Pengelolaan kini di detail satu perintah; daftar hanya pintu pembuatannya.
    assert "Buka detail perintah" in h
    assert "/barang-keluar?buka=tambah_barang_keluar" not in h
    # Tombol "Pengambilan barang jasa" sejajar dengan "Buat perintah" —
    # keluhan pemilik 11 Oktober 2026: aksinya sudah ada lebih dulu lewat
    # laci, tapi tak punya pintu sendiri di halaman ini, jadi tak kelihatan
    # bedanya dari penjualan barang pabrik.
    assert "/barang-keluar?buka=ambil_jasa" in h, \
        "tombol pengambilan jasa tak ada di halamannya"


async def test_operator_melihat_halamannya_tetapi_tak_ditawari_tombolnya(pg, gudang):
    """Pemilik menyebut tombolnya untuk Admin & Super Admin.

    HALAMANNYA tetap terbuka untuk operator — ia perlu tahu apa yang sudah dan
    akan keluar dari gudangnya. Tugasnya sendiri sampai lewat KARTU di Antrian
    tunggu, bukan dari halaman ini: di app ini tugas selalu sampai lewat kartu,
    dan operator yang harus membuka halaman lain untuk tahu ada pekerjaan akan
    melewatkannya.
    """
    await _perintah(pg, gudang, karung=40)
    c = await _klien(pg, gudang["op"], "uji_tombol_op", mode="operator")
    async with c:
        r = await c.get("/barang-keluar")
    assert r.status_code == 200, r.status_code
    h = r.text
    assert "OUT-" in h, "operator tak bisa melihat isi halamannya"
    assert "buka=perintah_keluar" not in h, "operator ditawari tombol memerintah"
    assert "buka=ambil_jasa" not in h, "operator ditawari tombol pengambilan jasa"


async def test_rantai_barang_keluar_tak_lagi_digambar_di_katalog(pg, gudang):
    """Dicabut dari "Catat pekerjaan lain" — DAN tetap dikirim di menu.

    Keduanya perlu, dan yang kedua mudah terlewat: lembar yang dibuka tombol
    maupun kartu dibangun dari spesifikasi yang SAMA. Aksi yang dibuang dari
    menu berarti tombolnya membuka lembar kosong.
    """
    c = await _klien(pg, gudang["adm"], "uji_katalog_admin")
    async with c:
        r = await c.get("/api/actions/menu")
    daftar = r.json()
    if isinstance(daftar, dict):
        daftar = daftar.get("aksi") or daftar.get("actions") or []
    peta = {a["id"]: a for a in daftar}
    for aksi in ("perintah_keluar", "tambah_barang_keluar",
                 "batal_perintah_keluar", "verifikasi_keluar",
                 "muat_semua", "muat_barang", "selesai_muat"):
        assert aksi in peta, f"{aksi} hilang dari menu — lembarnya akan kosong"
        assert peta[aksi].get("kartu"), (
            f"{aksi} masih digambar di katalog Catat pekerjaan lain")


# ───────── Menambah barang: sampai sebelum diverifikasi, dan digabung ────────

async def test_item_yang_sudah_ada_dijumlah_bukan_jadi_baris_kedua(pg, gudang):
    """Keputusan pemilik 29 September 2026: "jika item sudah ada berarti jumlah
    yang keluar ditambahkan, jika belum ada berarti itemnya ditambahkan."

    Dua baris untuk barang yang sama membuat kartunya menyebut "Beras Medium"
    dua kali dengan angka berbeda, dan yang membacanya menjumlah sendiri — lalu
    salah sekali dari sepuluh.
    """
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=40)          # 1.000 kg
    async with pg() as db:
        h = await bk.tambah_baris(
            db, user=await db.get(User, gudang["adm"]), rec_id=r.rec.id,
            baris=bk.BarisPerintah(tipe="finished_goods", sku_id=gudang["sku"],
                                   std_id=gudang["std"], jumlah_karung=20))
    assert len(h.baris) == 1, "barang yang sama melahirkan baris kedua"
    it = h.baris[0]
    assert float(it.berat_perintah_kg) == 1_500, float(it.berat_perintah_kg)
    assert it.jumlah_karung_perintah == 60, it.jumlah_karung_perintah
    # Masih `perintah`, jadi stok BELUM tersentuh.
    assert float(it.berat_kg or 0) == 0
    assert await _stok(pg, gudang) == 10_000


async def test_item_yang_belum_ada_jadi_baris_baru(pg, gudang):
    """Sisi lain, dan ia wajib ada: "digabung" mudah dikerjakan dengan cara yang
    salah — menjumlahkan apa pun ke baris pertama, lalu satu truk berisi tiga
    macam barang tercatat sebagai satu baris beras."""
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.penggilingan.inventory.finished_goods import catat_bekatul
    from app.services import barang_keluar as bk
    from sqlalchemy import select

    async with pg() as db:
        proc = (await db.execute(select(PolishingProcess))).scalars().first()
        db.add(PolishingOutputLog(polishing_process_id=proc.id, jenis="bekatul",
                                  berat_kg=2_000, waktu_update=now_local(),
                                  input_by=gudang["op"]))
        await db.commit()
        await catat_bekatul(db, user=await db.get(User, gudang["op"]),
                            kode_pol=proc.kode_proses, berat_kg=2_000)

    r = await _perintah(pg, gudang, karung=40)
    async with pg() as db:
        h = await bk.tambah_baris(
            db, user=await db.get(User, gudang["adm"]), rec_id=r.rec.id,
            baris=bk.BarisPerintah(tipe="byproduct_curah", jenis="bekatul",
                                   berat_kg=500))
    assert len(h.baris) == 2, "barang berbeda tak melahirkan barisnya sendiri"


async def test_pk_dari_lot_berbeda_tak_pernah_digabung(pg, gudang):
    """Ketelusuran PK ke pemasok lewat LOT-nya. Dua lot yang dijumlah jadi satu
    baris menghapus jalan pulang itu tanpa satu pesan pun."""
    from app.database import now_local
    from app.models import MillingProcess, MillingProgressLog, User
    from app.services import barang_keluar as bk

    pid = []
    async with pg() as db:
        for kode in ("LOT-GAB-01", "LOT-GAB-02"):
            p = MillingProcess(kode_proses=kode, status="selesai",
                               silo_id=gudang["silo"], berat_gabah_masuk_kg=8_000,
                               waktu_mulai=now_local(), waktu_selesai=now_local(),
                               created_by=gudang["op"])
            db.add(p)
            await db.flush()
            db.add(MillingProgressLog(milling_process_id=p.id,
                                      berat_kumulatif_kg=4_000,
                                      waktu_update=now_local(),
                                      input_by=gudang["op"]))
            pid.append(p.id)
        await db.commit()

    klien = await _pelanggan(pg, "Pabrik Seberang")
    async with pg() as db:
        u = await db.get(User, gudang["adm"])
        r = await bk.buat_perintah(
            db, user=u,
            baris=[bk.BarisPerintah(tipe="pk_langsung", milling_process_id=pid[0],
                                    berat_kg=1_000)],
            pelanggan_id=klien)
    async with pg() as db:
        h = await bk.tambah_baris(
            db, user=await db.get(User, gudang["adm"]), rec_id=r.rec.id,
            baris=bk.BarisPerintah(tipe="pk_langsung", milling_process_id=pid[1],
                                   berat_kg=800))
    assert len(h.baris) == 2, "PK dua lot digabung — ketelusurannya hilang"


async def test_menambah_sesudah_dimuat_mengubah_perintah_saja(pg, gudang):
    """Tambahan perintah membuka tugas operator, aktual dan stok tetap."""
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=40)          # 1.000 kg
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                            rec_id=r.rec.id)
    assert await _stok(pg, gudang) == 9_000

    async with pg() as db:
        h = await bk.tambah_baris(
            db, user=await db.get(User, gudang["adm"]), rec_id=r.rec.id,
            baris=bk.BarisPerintah(tipe="finished_goods", sku_id=gudang["sku"],
                                   std_id=gudang["std"], jumlah_karung=20))
    it = h.baris[0]
    assert float(it.berat_perintah_kg) == 1_500, float(it.berat_perintah_kg)
    assert float(it.berat_kg) == 1_000, float(it.berat_kg)
    assert await _stok(pg, gudang) == 9_000, "perintah mengubah muatan aktual"
    assert h.rec.status == "perintah"
    # Dan tak melahirkan selisih palsu di kartu verifikasi Admin.
    from app.services.berjalan import untuk_staff
    async with pg() as db:
        b = await untuk_staff(db)
    assert r.rec.kode not in {x.kode for x in b.meja}
    c = await _klien(pg, gudang["adm"], "uji_tambah_tanpa_selisih")
    async with c:
        h = (await c.get(f"/barang-keluar/{r.rec.id}")).text
    assert "kurang 500" not in h


async def test_yang_sudah_diverifikasi_tak_bisa_ditambah_lagi(pg, gudang):
    """"selagi belum diverifikasi" — sesudahnya tidak.

    Menambah barang ke transaksi yang angkanya sudah diakui Admin berarti
    mengubah angka yang sudah jadi dasar keputusan, tanpa siapa pun melihatnya
    lagi.
    """
    from app.models import User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=40)
    async with pg() as db:
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]), rec_id=rid)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.tambah_baris(
                db, user=await db.get(User, gudang["adm"]), rec_id=rid,
                baris=bk.BarisPerintah(tipe="finished_goods", sku_id=gudang["sku"],
                                       std_id=gudang["std"], jumlah_karung=10))
    assert "ditutup" in str(e.value).lower(), str(e.value)


async def test_tombol_perintah_berdiri_di_puncak_halaman(pg, gudang):
    """Permintaan pemilik: "tombol perintah barang keluar dibuat paling atas
    saja."

    Semula ia di kaki. Halaman ini bisa panjang, dan tombol yang menuntut
    digulung dulu adalah tombol yang tak ditemukan orang yang sedang terburu.
    """
    await _perintah(pg, gudang, karung=40)
    c = await _klien(pg, gudang["adm"], "uji_puncak_admin")
    async with c:
        r = await c.get("/barang-keluar")
    h = r.text
    assert "buka=perintah_keluar" in h
    # Tombolnya mendahului kartu pertama.
    assert h.index("buka=perintah_keluar") < h.index("OUT-"), \
        "tombol perintah masih di bawah daftar kartunya"


async def test_kartu_di_halaman_membawa_tombolnya_sendiri(pg, gudang):
    """Daftar mengantar ke detail; tindakan tetap mengikuti status dan peran."""
    from app.models import User
    from app.services import barang_keluar as bk
    belum=await _perintah(pg,gudang,karung=40,pembeli="Belum Dimuat")
    sudah=await _perintah(pg,gudang,karung=20,pembeli="Sudah Dimuat")
    async with pg() as db:
        await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=sudah.rec.id)
    c=await _klien(pg,gudang['adm'],'uji_tombol_detail_adm')
    async with c:
        h=(await c.get('/barang-keluar')).text
        assert f'href="/barang-keluar/{belum.rec.id}"' in h
        assert f'href="/barang-keluar/{sudah.rec.id}"' in h
        a=(await c.get(f'/barang-keluar/{belum.rec.id}')).text
        b=(await c.get(f'/barang-keluar/{sudah.rec.id}')).text
    assert 'buka=batal_perintah_keluar' in a
    assert 'buka=verifikasi_keluar' not in a
    assert 'buka=verifikasi_keluar' in b
    assert 'buka=muat_semua' not in a+b
    c=await _klien(pg,gudang['op'],'uji_tombol_detail_op',mode='operator')
    async with c:
        h=(await c.get(f'/barang-keluar/{belum.rec.id}')).text
    assert 'buka=muat_semua' in h and 'buka=selesai_muat' in h
    assert 'buka=verifikasi_keluar' not in h
    assert 'buka=batal_perintah_keluar' not in h
    assert 'Ubah jumlah' not in h


async def test_tombol_kartu_mengunci_transaksinya(pg, gudang):
    """Yang menekan dari kartunya sudah memilih transaksinya — menanyakannya
    lagi adalah kesempatan memilih yang salah."""
    r = await _perintah(pg, gudang, karung=40)
    c = await _klien(pg, gudang["adm"], "uji_tombol_kunci")
    async with c:
        h = (await c.get(f"/barang-keluar/{r.rec.id}")).text
    assert f"buka=tambah_barang_keluar&nilai={r.rec.id}" in h, \
        "tombol kartu tak membawa transaksinya"


async def test_tombolnya_membuka_lembar_di_halaman_ini(pg, gudang):
    """Keluhan pemilik 29 September 2026: "mengapa kalau verifikasi barang
    keluar halamannya pindah ke antrian tunggu? begitu juga jika input perintah
    barang keluar."

    Sebabnya tombolnya menunjuk `/aksi?buka=…` — pola PINTASAN, yang lahir
    untuk kaki halaman Antrian tunggu, tempat "pindah halaman" tak terasa sebab
    halamannya itu-itu juga. Dari sini ia jadi perjalanan: orang yang sedang
    membaca kartu OUT- tiba-tiba berdiri di daftar pekerjaan gudang, dan
    sesudah menyimpan ia harus mencari jalan kembali.

    Tiga hal yang harus benar bersamaan, dan yang ketiga paling mudah terlupa —
    tanpa `aksi.js`, menekan tombolnya cuma memuat ulang halaman dengan
    `?buka=` dan tak ada yang menangkapnya. Tombol yang tak melakukan apa-apa
    lebih buruk daripada tombol yang tak ada (pelajaran layar Stok, 26
    September).
    """
    await _perintah(pg, gudang, karung=40)
    c = await _klien(pg, gudang["adm"], "uji_lembar_di_tempat")
    async with c:
        h = (await c.get("/barang-keluar")).text

    assert "/aksi?buka=" not in h, "tombolnya masih melemparkan orang ke /aksi"
    assert "/barang-keluar?buka=perintah_keluar" in h
    assert '<dialog class="lembar" id="lembar">' in h, "halaman ini bukan tuan rumah lembarnya"
    assert "aksi.js" in h, "aksi.js tak dimuat — tombolnya takkan menangkap apa pun"


async def test_operator_pun_mendapat_lembarnya(pg, gudang):
    """Syaratnya `BOLEH_PERINTAH or BOLEH_MUAT`, bukan salah satunya.

    Layar Stok pernah memuat lembarnya hanya untuk yang boleh mengubah, dan
    akibatnya tombol "Minta lot ini" milik operator tak pernah bisa membuka
    borangnya — persis kesalahan yang sama menunggu di sini.
    """
    r = await _perintah(pg, gudang, karung=40)
    c = await _klien(pg, gudang["op"], "uji_lembar_op", mode="operator")
    async with c:
        h = (await c.get(f"/barang-keluar/{r.rec.id}")).text
    assert f"/barang-keluar/{r.rec.id}?buka=muat_semua" in h
    assert '<dialog class="lembar" id="lembar">' in h, \
        "operator punya tombol tetapi tak punya lembarnya"
    assert "aksi.js" in h


async def test_catat_pekerjaan_lain_berdiri_tepat_di_atas_pengaturan():
    """Permintaan pemilik 29 September 2026: "catat pekerjaan lain posisinya
    diatas pengaturan saja."

    Urutan laci ini urutan SEBERAPA SERING, bukan urutan alur kerja — yang
    paling sering dibuka berdiri paling dekat ibu jari. Dan katalog ini memang
    bukan pekerjaan harian lagi: sejak barang keluar, packing, bekatul, dan
    pembatalan punya pintunya masing-masing, yang tersisa cuma QC, pembelian
    karung, dan pencocokan tiket.
    """
    from app.web.nav import TAB

    urut = [t[0] for t in TAB]
    assert urut[-2:] == ["aksi_lain", "pengaturan"], urut[-4:]


# ─────────── Jalan kembali: pembatalan input terakhir (29 Sep 2026) ───────────
#
# Rantai ini dibuat supaya kesalahan TERTANGKAP di langkah verifikasi Admin.
# Sampai 29 September 2026 ia bisa menangkap tanpa bisa membetulkan: `batalkan`
# menolak yang sudah dimuat (benar — barangnya di atas truk), dan pembatalan
# input terakhir tak mengenal `outgoing_records` sama sekali. Berkas uji ini
# menjaga pintu itu tetap ada, dan tetap mengembalikan angka yang benar.


async def _undo(pg, uid, scope="semua"):
    from app.models import User
    from app.services import undo
    async with pg() as db:
        u = await db.get(User, uid)
        c = await undo.cakupan(db, scope=scope, nama=None, self_id=u.id)
        pesan = await undo.undo_last(db, actor=u, cakupan=c)
        await db.commit()
        return pesan


async def test_rantai_barang_keluar_masuk_daftar_yang_bisa_dibatalkan():
    """Pagar paling murah, dan yang paling menolong: tabelnya ADA di daftarnya.

    `undo_last` menolak apa pun yang tabelnya tak terdaftar — sebelum penangan
    mana pun dipanggil. Jadi seluruh penangan di bawah bisa benar seluruhnya
    dan pintunya tetap tertutup, tanpa satu pun uji lain yang memberi tahu.
    """
    from app.services.undo import _UNDOABLE

    assert "outgoing_records" in _UNDOABLE, \
        "rantai barang keluar tak punya jalan kembali sama sekali"


async def test_pencatatan_muat_bisa_dibatalkan_dan_stoknya_pulih(pg, gudang):
    """Ketukan "dimuat semua" yang salah harus bisa ditarik, dan stoknya pulih.

    Inilah keadaan yang tak punya jalan mana pun sebelum hari ini: operator
    menekan "dimuat" atas perintah yang salah, stok berkurang 2.500 kg atas
    beras yang masih bertumpuk, dan `batalkan` menolak sebab statusnya sudah
    bukan `perintah`.
    """
    from app.models import OutgoingRecord, User
    from app.penggilingan.inventory.models import OUT_PERINTAH
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                            rec_id=r.rec.id)
    assert await _stok(pg, gudang) == 7_500

    pesan = await _undo(pg, gudang["op"])
    assert "pencatatan muat" in pesan.lower(), pesan
    assert await _stok(pg, gudang) == 10_000, "stok tak pulih sesudah dibatalkan"
    async with pg() as db:
        rec = await db.get(OutgoingRecord, r.rec.id)
        assert rec.status == OUT_PERINTAH, "kartunya tak kembali ke antrean muat"
        assert rec.dimuat_oleh is None and rec.waktu_muat is None, \
            "masih tertulis siapa yang memuatnya"


async def test_pembatalan_muat_tak_menyentuh_baris_yang_dicatat_operator_sendiri(
        pg, gudang):
    """Dua ketukan berbeda, dua jalan kembali berbeda.

    Operator mencatat satu baris sendiri (karena muatannya berselisih), lalu
    menekan "selesai". Yang dibatalkan hanya PENUTUPANNYA; angka yang ia catat
    sendiri tetap berdiri, sebab bukan ketukan itu yang mengisinya. Kalau ikut
    dinol-kan, satu pembatalan menghapus dua pencatatan — yang kedua tanpa
    diminta siapa pun, dan tanpa satu pun kalimat yang menyebutnya.
    """
    from sqlalchemy import select

    from app.models import OutgoingItem, OutgoingRecord, User
    from app.penggilingan.inventory.models import OUT_PERINTAH
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        it = (await db.execute(select(OutgoingItem).where(
            OutgoingItem.outgoing_record_id == r.rec.id))).scalars().first()
        await bk.catat_muatan(db, user=await db.get(User, gudang["op"]),
                              item_id=it.id, jumlah_karung=80)
        await bk.selesai_muat(db, user=await db.get(User, gudang["op"]),
                              rec_id=r.rec.id, sebab="Truk penuh; sisa tidak terkirim")
    assert await _stok(pg, gudang) == 8_000        # 80 × 25 kg keluar

    pesan = await _undo(pg, gudang["op"])
    assert "pencatatan muat" in pesan.lower(), pesan
    async with pg() as db:
        rec = await db.get(OutgoingRecord, r.rec.id)
        it = (await db.execute(select(OutgoingItem).where(
            OutgoingItem.outgoing_record_id == r.rec.id))).scalars().first()
        assert rec.status == OUT_PERINTAH, "tak kembali ke antrean muat"
        assert float(it.berat_kg) == 2_000, \
            "angka yang dicatat operator sendiri ikut terhapus"
    assert await _stok(pg, gudang) == 8_000, "stok bergerak tanpa diminta"


async def test_muat_baris_kembali_ke_angka_sebelumnya_bukan_nol(pg, gudang):
    """Baris yang dicatat 100 karung lalu diperbaiki jadi 80 harus kembali ke 100.

    "Kembalikan saja ke nol" adalah tebakan yang paling menggoda dan salah
    justru di sini: yang kembali ke nol menaikkan stok atas 100 karung yang
    masih tertulis di catatan, dan tak ada satu pun angka di layar yang
    menunjukkannya.
    """
    from sqlalchemy import select

    from app.models import OutgoingItem, User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        it = (await db.execute(select(OutgoingItem).where(
            OutgoingItem.outgoing_record_id == r.rec.id))).scalars().first()
        u = await db.get(User, gudang["op"])
        await bk.catat_muatan(db, user=u, item_id=it.id, jumlah_karung=100)
        await bk.catat_muatan(db, user=u, item_id=it.id, jumlah_karung=80)
    assert await _stok(pg, gudang) == 8_000

    pesan = await _undo(pg, gudang["op"])
    assert "2.500" in pesan, pesan
    async with pg() as db:
        it = (await db.execute(select(OutgoingItem).where(
            OutgoingItem.outgoing_record_id == r.rec.id))).scalars().first()
        assert float(it.berat_kg) == 2_500, "tak kembali ke angka sebelumnya"
        assert it.jumlah_karung == 100, "jumlah karungnya tak ikut kembali"
    assert await _stok(pg, gudang) == 7_500


async def test_verifikasi_bisa_dibatalkan_dan_kode_timbangnya_dilepas(pg, gudang):
    """Verifikasi yang menempel tiket SALAH harus bisa ditarik — dan tiketnya
    kembali bebas, kalau tidak tiket yang benar tak bisa ditempel ke mana pun
    dan tak ada layar yang bisa menjelaskan sebabnya.

    STOK TIDAK BERGERAK di langkah ini, dan itu yang diuji berdampingan:
    barangnya berpindah saat DIMUAT, bukan saat diverifikasi.
    """
    from app.models import OutgoingRecord, User
    from app.penggilingan.gudang1.services.timbang_link import tiket_keluar_aktif
    from app.penggilingan.inventory.models import OUT_DIMUAT
    from app.services import barang_keluar as bk

    tid = await _tiket(pg, "TK-UNDO-1")
    rid = await _sampai_dimuat(pg, gudang, karung=100)
    async with pg() as db:
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=rid, timbangan_transaksi_id=tid)
    assert await _stok(pg, gudang) == 7_500

    pesan = await _undo(pg, gudang["adm"])
    assert "verifikasi" in pesan.lower(), pesan
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        assert rec.status == OUT_DIMUAT, "tak kembali menunggu verifikasi"
        assert rec.timbangan_transaksi_id is None, "kode timbangnya masih menempel"
        assert rec.diverifikasi_oleh is None and rec.waktu_verifikasi is None
        assert tid in {t["id"] for t in await tiket_keluar_aktif(db)}, \
            "tiketnya tetap terhitung terpakai — tak bisa ditempel ke mana pun"
    assert await _stok(pg, gudang) == 7_500, "pembatalan verifikasi menggerakkan stok"


async def test_muat_tak_bisa_dibatalkan_selagi_verifikasinya_masih_berdiri(
        pg, gudang):
    """Satu langkah pada satu ketukan — dan penolakannya MENYEBUT langkah yang
    harus dibatalkan lebih dulu.

    "Statusnya bukan dimuat" tak menolong siapa pun. Yang menolong adalah
    "batalkan verifikasinya dulu", sebab itulah yang ditanyakan orang yang
    sedang memegang HP-nya.
    """
    from app.models import User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=40)
    async with pg() as db:
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]), rec_id=rid)
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.balik_muat(db, rec_id=rid, diisi=[])
    assert "verifikasinya" in str(e.value), str(e.value)


async def test_penerbitan_perintah_bisa_ditarik_dan_operator_dikabari(pg, gudang):
    """Perintah yang lenyap dari antrean tanpa kabar akan ditanyakan sepanjang
    hari — dan ditanyakan kepada orang yang tak menekan apa pun."""
    from sqlalchemy import select

    from app.models import Notification, OutgoingRecord
    from app.penggilingan.inventory.models import OUT_BATAL

    r = await _perintah(pg, gudang, karung=100)
    pesan = await _undo(pg, gudang["adm"])
    assert "penerbitan perintah" in pesan.lower(), pesan
    async with pg() as db:
        rec = await db.get(OutgoingRecord, r.rec.id)
        assert rec.status == OUT_BATAL
        assert (rec.sebab_batal or "").strip(), "batal tanpa sebab tertulis"
        kabar = (await db.execute(select(Notification).where(
            Notification.table_name == "outgoing_records",
            Notification.record_id == r.rec.id,
            Notification.target_role == "operator"))).scalars().all()
        assert any("DITARIK" in k.pesan for k in kabar), \
            "operator tak dikabari bahwa tugasnya hangus"
    assert await _stok(pg, gudang) == 10_000, "perintah yang ditarik menyentuh stok"


async def test_pembatalan_perintah_pun_bisa_ditarik_kembali(pg, gudang):
    """Admin yang salah membatalkan perintah orang lain harus bisa menghidupkannya
    kembali — kalau tidak, satu salah ketuk berarti perintah diketik ulang dari
    awal, dan yang diketik ulang kehilangan kode OUT- yang sudah disebut di
    telepon."""
    from app.models import OutgoingRecord, User
    from app.penggilingan.inventory.models import OUT_PERINTAH
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        await bk.batalkan(db, user=await db.get(User, gudang["adm"]),
                          rec_id=r.rec.id, sebab="salah pembeli")
    pesan = await _undo(pg, gudang["adm"])
    assert "pembatalan perintah" in pesan.lower(), pesan
    async with pg() as db:
        rec = await db.get(OutgoingRecord, r.rec.id)
        assert rec.status == OUT_PERINTAH, "perintahnya tak hidup lagi"
        assert rec.sebab_batal is None, "sebab pembatalan lama masih menempel"


async def test_jejak_muat_membawa_cuplikan_keadaan_sebelumnya(pg, gudang):
    """Cuplikan itu yang membuat pembatalannya mungkin — dan ia HARUS ditulis
    saat langkahnya terjadi. Sesudahnya, kedua macam baris (yang diisi ketukan
    itu dan yang dicatat operator lebih dulu) sama-sama berisi angka, dan tak
    ada cara membedakannya lagi."""
    from sqlalchemy import select

    from app.models import ActivityLog, User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                            rec_id=r.rec.id)
    async with pg() as db:
        log = (await db.execute(
            select(ActivityLog)
            .where(ActivityLog.aksi == "barang_keluar_muat",
                   ActivityLog.record_id == r.rec.id)
            .order_by(ActivityLog.id.desc()).limit(1))).scalars().first()
    assert log is not None, "langkah muat tak meninggalkan jejak"
    assert log.field_name == "diisi", log.field_name
    assert (log.old_value or "").strip(), \
        "jejaknya tak menyebut baris mana yang diisi ketukan itu"


async def test_layar_menawarkan_pembatalan_barang_keluar_sebagai_didukung(pg, gudang):
    """Pratinjaunya harus berkata DIDUKUNG, bukan cuma penangannya yang ada.

    Tombolnya digambar dari `Pratinjau.didukung`; penangan yang benar di
    belakang tombol yang berkata "belum bisa" tak pernah dijalankan siapa pun.
    """
    from app.models import User
    from app.services import undo

    await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        u = await db.get(User, gudang["adm"])
        c = await undo.cakupan(db, scope="saya", nama=None, self_id=u.id)
        p = await undo.pratinjau_terakhir(db, cakupan=c)
    assert p is not None and p.tabel == "outgoing_records", p
    assert p.didukung, "layar masih berkata barang keluar belum bisa dibatalkan"


# ─────────── Pembeli ditautkan ke pelanggan Kledo (29 Sep 2026) ───────────
#
# Permintaan pemilik: "nama pembeli di barang keluar sinkronkan dengan
# pelanggan di kledo". Sebabnya terlihat sesudah sepekan dipakai: teks bebas
# melahirkan "Toko Makmur", "toko makmur", dan "TK Makmur" untuk satu pembeli.
#
# Yang dijaga di sini bukan cuma tautannya ADA, melainkan DUA hal yang mudah
# rusak diam-diam: nama yang tercatat harus sama dengan yang dipilih, dan
# pintu daruratnya (pembeli yang belum ada di Kledo) harus tetap terbuka —
# penyegaran kontaknya mingguan.


async def _pelanggan(pg, nama, *, status="aktif", dihapus=False, kledo=None):
    from app.database import now_local
    from app.models import Pelanggan
    async with pg() as db:
        p = Pelanggan(nama_pelanggan=nama, status=status,
                      kledo_contact_id=kledo,
                      deleted_at=now_local() if dihapus else None)
        db.add(p)
        await db.commit()
        return p.id


async def _perintah_pembeli(pg, g, *, pelanggan_id=None, karung=40):
    from app.models import User
    from app.services import barang_keluar as bk
    async with pg() as db:
        return await bk.buat_perintah(
            db, user=await db.get(User, g["adm"]),
            baris=[bk.BarisPerintah(tipe="finished_goods", sku_id=g["sku"],
                                    std_id=g["std"], jumlah_karung=karung)],
            pelanggan_id=pelanggan_id)


async def test_pembeli_dipilih_dari_daftar_kledo_tersimpan_bertaut(pg, gudang):
    """Tautannya yang membuat "apa saja yang keluar ke pembeli ini" punya
    jawaban tunggal — dan kelak bisa dicocokkan dengan faktur Kledo tanpa
    mencocokkan ejaan."""
    pid = await _pelanggan(pg, "PT Beras Jaya", kledo=90_001)
    r = await _perintah_pembeli(pg, gudang, pelanggan_id=pid)
    assert r.rec.pelanggan_id == pid, "pembelinya tak tertaut ke master"
    assert r.rec.nama_pembeli == "PT Beras Jaya", \
        "cuplikan namanya tak ikut tersimpan"


async def test_pembeli_yang_belum_ada_di_kledo_tak_lagi_boleh_diketik(pg, gudang):
    """Kotak ketik-bebas ("PINTU DARURAT" untuk pembeli yang belum tersinkron
    dari Kledo) DICABUT (keputusan pemilik 11 Oktober 2026: "field pembeli
    baru hapus saja") — `buat_perintah` tak menerima parameter nama lagi
    sama sekali, cuma `pelanggan_id`. Pelanggan baru didaftarkan dulu di
    Kledo sebelum bisa dipilih di sini.
    """
    from app.services import barang_keluar as bk
    import inspect

    assert "nama_pembeli" not in inspect.signature(bk.buat_perintah).parameters


async def test_perintah_tanpa_pembeli_ditolak_menyebut_satu_satunya_jalan(
        pg, gudang):
    """Yang ditolak tanpa diberi tahu jalan keluarnya akan dicoba lagi dengan
    cara yang sama."""
    from app.services import barang_keluar as bk

    with pytest.raises(bk.BarangKeluarError) as e:
        await _perintah_pembeli(pg, gudang)
    pesan = str(e.value)
    assert "daftar" in pesan.lower() and "kledo" in pesan.lower(), pesan
    # Dan TAK lagi menyebut jalan ketik-bebas yang sudah dicabut.
    assert "tulis" not in pesan.lower(), pesan


async def test_pelanggan_nonaktif_atau_terhapus_ditolak(pg, gudang):
    """Yang DITAWARKAN dan yang DITERIMA wajib himpunan yang sama.

    Daftar pilihannya menyaring `status = 'aktif'` dan `deleted_at IS NULL`;
    kalau layanannya tidak, lembar yang sudah lama terbuka di layar seseorang
    masih bisa menautkan ke pelanggan yang sudah dinonaktifkan di Kledo —
    lolos tanpa satu pun tanda, dan baru jadi pertanyaan saat laporan dibuka.
    """
    from app.services import barang_keluar as bk

    mati = await _pelanggan(pg, "CV Sudah Tutup", status="nonaktif")
    hapus = await _pelanggan(pg, "CV Terhapus", dihapus=True)
    for pid in (mati, hapus):
        with pytest.raises(bk.BarangKeluarError) as e:
            await _perintah_pembeli(pg, gudang, pelanggan_id=pid)
        assert "daftar" in str(e.value).lower(), str(e.value)


async def test_daftar_pelanggan_menawarkan_yang_aktif_saja(pg, gudang):
    """Dan daftarnya dibaca dari CERMIN LOKAL, bukan dari Kledo.

    Kalau rute ini memanggil Kledo, borang perintah muat tak bisa dibuka saat
    Kledo lambat atau mati — pabrik berhenti karena layanan akuntansi pihak
    ketiga. `KLEDO_API_KEY` pun tak perlu ada di layanan ini.
    """
    import inspect

    from app.web.aksi_inventory import pelanggan_kledo

    await _pelanggan(pg, "PT Aktif")
    await _pelanggan(pg, "CV Nonaktif", status="nonaktif")
    await _pelanggan(pg, "CV Dihapus", dihapus=True)

    sumber = inspect.getsource(pelanggan_kledo)
    assert "kledo.com" not in sumber and "urlopen" not in sumber, \
        "rute daftar pelanggan memanggil Kledo langsung dari layanan produksi"

    from app.models import User
    async with pg() as db:
        u = await db.get(User, gudang["adm"])
    daftar = await pelanggan_kledo(user=u)
    nama = {d["label"] for d in daftar}
    assert "PT Aktif" in nama
    assert "CV Nonaktif" not in nama and "CV Dihapus" not in nama, sorted(nama)
    # Nilainya harus BISA dipakai kembali — id, bukan namanya.
    pid = next(d["value"] for d in daftar if d["label"] == "PT Aktif")
    r = await _perintah_pembeli(pg, gudang, pelanggan_id=int(pid))
    assert r.rec.nama_pembeli == "PT Aktif"


# ─── Umpan balik lapangan 30 September 2026: curah & selisih timbang ───


async def _bekatul_curah(pg, gudang, kg_=2_000):
    """Catat bekatul curah dari penyosohan yang sudah ada di fixture."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.penggilingan.inventory.finished_goods import catat_bekatul

    async with pg() as db:
        proc = (await db.execute(select(PolishingProcess))).scalars().first()
        db.add(PolishingOutputLog(polishing_process_id=proc.id, jenis="bekatul",
                                  berat_kg=kg_, waktu_update=now_local(),
                                  input_by=gudang["op"]))
        await db.commit()
        await catat_bekatul(db, user=await db.get(User, gudang["op"]),
                            kode_pol=proc.kode_proses, berat_kg=kg_)


async def test_bekatul_curah_ditawarkan_di_daftar_barang_keluar(pg, gudang):
    """⛔ REGRESI YANG DIJAGA DI SINI: bekatul curah tak bisa keluar sama sekali.

    Dua perubahan yang masing-masing BENAR membuka lubang di antaranya. Aksi
    lama "Bekatul keluar" dibuang 28 September (pintu lama ditutup), dan daftar
    barang keluar melewati barang tanpa karung dengan alasan "curah punya jalur
    sendiri" (pintu baru melewatinya) — padahal jalur sendiri itu sudah tidak
    ada. Akibatnya bekatul curah masuk terus dan angka stoknya hanya bisa naik,
    tanpa satu pun pesan galat. Laporan operator 30 September 2026.
    """
    from app.models import User
    from app.web.aksi_inventory import barang_bisa_keluar

    await _bekatul_curah(pg, gudang, 2_000)
    async with pg() as db:
        u = await db.get(User, gudang["adm"])
    daftar = await barang_bisa_keluar(user=u)
    curah = [d for d in daftar if d["value"].startswith("cr:")]
    assert curah, f"bekatul curah tak ada di daftar: {[d['value'] for d in daftar]}"
    assert curah[0]["value"] == "cr:bekatul", curah[0]
    # SATUANNYA di label: kotak jumlahnya satu dan tak bisa berganti tulisan
    # mengikuti pilihan, jadi "100" pada baris curah harus jelas 100 kg.
    assert "kg" in curah[0]["label"], curah[0]["label"]


async def test_picker_bekatul_mengikuti_packing_otomatis_kartu_stok(pg, gudang):
    """100 kg bekatul = 2 karung otomatis ×40 kg + 20 kg curah.

    Picker sebelumnya menampilkan saldo mentah byproduct_stock sebesar 60 kg,
    padahal kartu stok memisahkan 40 kg menjadi kemasan otomatis dan menyisakan
    20 kg curah.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.web.aksi_inventory import barang_bisa_keluar

    await _bekatul_curah(pg, gudang, 60)
    async with pg() as db:
        proc = (await db.execute(select(PolishingProcess))).scalars().first()
        db.add(PolishingOutputLog(
            polishing_process_id=proc.id, jenis="bekatul", berat_kg=40,
            waktu_update=now_local(), input_by=gudang["op"]))
        await db.commit()
        u = await db.get(User, gudang["adm"])
    daftar = await barang_bisa_keluar(user=u)
    curah = next(d for d in daftar if d["value"] == "cr:bekatul")
    assert "2 karung × 40 kg otomatis" in curah["label"], curah["label"]
    assert "20 kg curah" in curah["label"], curah["label"]
    assert "total 100 kg" in curah["label"], curah["label"]
    assert "60 kg tersedia" not in curah["label"], curah["label"]


async def test_bekatul_curah_benar_benar_keluar_dan_mengurangi_stok(pg, gudang):
    """Dan satuannya KILOGRAM — bukan karung.

    Yang ditawarkan tanpa bisa dikerjakan lebih buruk daripada yang tak
    ditawarkan: operator memilihnya, mengetik jumlah, lalu ditolak di depan
    truk.
    """
    from app.models import User
    from app.penggilingan.inventory.finished_goods import hitung_stok_bekatul
    from app.services import barang_keluar as bk
    from app.web.aksi_inventory import _satu_baris

    klien = await _pelanggan(pg, "Peternakan Jaya")
    await _bekatul_curah(pg, gudang, 2_000)
    async with pg() as db:
        assert float(await hitung_stok_bekatul(db)) == 2_000
        baris = await _satu_baris(db, "cr:bekatul", 500)
        r = await bk.buat_perintah(
            db, user=await db.get(User, gudang["adm"]), baris=[baris],
            pelanggan_id=klien)
        await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                            rec_id=r.rec.id)
    async with pg() as db:
        assert float(await hitung_stok_bekatul(db)) == 1_500, \
            "bekatul curah keluar tanpa mengurangi stoknya"


async def test_barang_keluar_curah_membuka_karung_otomatis(pg, gudang):
    """8 kg curah + 1 karung 40 kg, keluar 20 kg → sisa curah 28 kg.

    Bekatul di lapangan satu tumpukan. Saldo curah yang kurang harus mengambil
    sisa dari karung, dan tampilan otomatis menghitung ulang kemasan dari total
    stok yang benar-benar tersisa.
    """
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingOutputLog
    from app.penggilingan.inventory.finished_goods import (
        FinishedGoodsStock, find_or_create_sku, hitung_stok_byproduct_total,
    )
    from app.services import barang_keluar as bk
    from app.services.stok import _packing_otomatis
    from sqlalchemy import select

    pelanggan_id = await _pelanggan(pg, "Peternakan Jaya")
    await _bekatul_curah(pg, gudang, 8)
    async with pg() as db:
        proc = (await db.execute(select(PolishingProcess))).scalars().first()
        # 8 kg sudah tercatat curah; 40 kg berikutnya keluar dari mesin lalu
        # dikemas. Packing memindahkan rumah stok, bukan menciptakan hasil.
        db.add(PolishingOutputLog(
            polishing_process_id=proc.id, jenis="bekatul", berat_kg=40,
            waktu_update=now_local(), input_by=gudang["op"]))
        sku = await find_or_create_sku(
            db, kategori="bekatul", material_kode="bekas", ukuran=40)
        db.add(FinishedGoodsStock(
            product_sku_id=sku.id, rice_quality_standard_id=None,
            source_type="polishing", source_id=proc.id, jumlah_karung=1,
            berat_total_kg=40, warehouse_id=None, waktu=now_local(),
            input_by=gudang["op"], jasa_id=None))
        await db.commit()
        assert await hitung_stok_byproduct_total(db, "bekatul") == 48
        perintah = await bk.buat_perintah(
            db, user=await db.get(User, gudang["adm"]),
            baris=[bk.BarisPerintah(tipe="byproduct_curah", jenis="bekatul",
                                    berat_kg=20)],
            pelanggan_id=pelanggan_id)
        await bk.muat_semua(db, user=await db.get(User, gudang["op"]),
                            rec_id=perintah.rec.id)

    async with pg() as db:
        sisa = await hitung_stok_byproduct_total(db, "bekatul")
        assert sisa == 28
        assert _packing_otomatis("bekatul", sisa) == (40, 0, 0, 28)


async def test_perintah_curah_melebihi_stok_ditolak_dengan_angkanya(pg, gudang):
    """Yang ditolak tanpa angka akan dicoba lagi dengan tebakan."""
    from app.models import User
    from app.services import barang_keluar as bk

    klien = await _pelanggan(pg, "Peternakan Jaya")
    await _bekatul_curah(pg, gudang, 2_000)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.buat_perintah(
                db, user=await db.get(User, gudang["adm"]),
                baris=[bk.BarisPerintah(tipe="byproduct_curah", jenis="bekatul",
                                        berat_kg=5_000)],
                pelanggan_id=klien)
    assert "2.000" in str(e.value), str(e.value)


async def test_selisih_timbang_besar_menuntut_sebab(pg, gudang):
    """Keputusan pemilik 30 September 2026: boleh tetap ditutup — truknya sudah
    berangkat berjam-jam sebelumnya — TETAPI ditandai, dan sebabnya wajib.

    Pertanyaan operator yang melahirkannya: satu mobil berisi beras DAN broken,
    bagaimana menimbangnya. Jawabannya total lawan total; yang belum ada adalah
    apa yang terjadi kalau totalnya berselisih jauh.
    """
    from app.models import OutgoingRecord, User
    from app.services import barang_keluar as bk

    # 100 karung × 25 kg = 2.500 kg dicatat; tiketnya 4.000 kg → beda 1.500 kg,
    # jauh di atas ambang (maks 100 kg atau 2% = 50 kg).
    rid = await _sampai_dimuat(pg, gudang, karung=100)
    tid = await _tiket(pg, "TK-BEDA-1", barang=4_000)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                                rec_id=rid, timbangan_transaksi_id=tid)
    pesan = str(e.value)
    assert "sebab" in pesan.lower(), pesan
    assert "1.500" in pesan, pesan

    async with pg() as db:
        rec, catatan = await bk.verifikasi(
            db, user=await db.get(User, gudang["adm"]), rec_id=rid,
            timbangan_transaksi_id=tid, sebab_selisih="terpal basah + palet")
    assert rec.status == "selesai", "ditahan padahal sebabnya sudah ditulis"
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        assert rec.sebab_selisih == "terpal basah + palet", rec.sebab_selisih


async def test_selisih_wajar_tak_menuntut_apa_apa(pg, gudang):
    """Karung tak persis 25,0 kg, dan truk membawa terpal. Menuntut alasan atas
    selisih sehari-hari akan membuat kolom sebabnya terisi "-" setiap kali —
    dan kolom yang selalu terisi sama berhenti jadi tanda."""
    from app.models import OutgoingRecord, User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=100)      # 2.500 kg
    tid = await _tiket(pg, "TK-BEDA-2", barang=2_530)        # beda 30 kg
    async with pg() as db:
        rec, _ = await bk.verifikasi(
            db, user=await db.get(User, gudang["adm"]), rec_id=rid,
            timbangan_transaksi_id=tid)
    assert rec.status == "selesai"
    async with pg() as db:
        assert (await db.get(OutgoingRecord, rid)).sebab_selisih is None, \
            "selisih wajar ikut ditandai — tandanya jadi tak berarti"


async def test_membatalkan_verifikasi_mencabut_tanda_selisihnya(pg, gudang):
    """Tandanya lahir dari perbandingan dengan tiket yang ikut dilepas.
    Tanda yang tertinggal tanpa tiketnya adalah tuduhan atas selisih yang tak
    bisa ditunjukkan lagi kepada siapa pun."""
    from app.models import OutgoingRecord, User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=100)
    tid = await _tiket(pg, "TK-BEDA-3", barang=4_000)
    async with pg() as db:
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=rid, timbangan_transaksi_id=tid,
                            sebab_selisih="palet ikut tertimbang")
    await _undo(pg, gudang["adm"])
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        assert rec.sebab_selisih is None, "tanda selisih tertinggal tanpa tiketnya"


# ──────────────────────── Auto-taut tiket keluar menganggur ────────────────
#
# Permintaan pemilik 4 Oktober 2026: tiket timbang keluar lama yang terlanjur
# menumpuk tanpa pasangan (lihat "Tiket timbang keluar terlewat" di atas)
# ditautkan OTOMATIS — bukan lewat nomor urut kode (dua penghitung yang tak
# berhubungan, lihat docstring `auto_tautkan`), melainkan pembeli + tanggal +
# berat dalam ambang wajar yang SAMA dipakai verifikasi manual.

async def test_auto_taut_menautkan_pasangan_yang_jelas(pg, gudang):
    from app.models import User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=100)        # 2.500 kg, Toko Makmur
    tid = await _tiket(pg, "TK-AUTO-01", barang=2_480)        # beda 20 kg — wajar
    async with pg() as db:
        hasil = await bk.auto_tautkan(db, user=await db.get(User, gudang["adm"]))
    assert hasil.tertaut == ["TK-AUTO-01 -> " + (await _kode(pg, rid))]
    assert hasil.dilewati == []

    from app.models import OutgoingRecord
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        assert rec.timbangan_transaksi_id == tid, "tak benar-benar tertaut"
        assert rec.status == "selesai"


async def _kode(pg, rid) -> str:
    from app.models import OutgoingRecord
    async with pg() as db:
        return (await db.get(OutgoingRecord, rid)).kode


async def test_auto_taut_melewati_pembeli_berbeda(pg, gudang):
    """Pembeli berbeda tak pernah jadi pasangan — berapa pun miripnya berat
    dan tanggalnya."""
    from app.models import OutgoingRecord, User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=100, pembeli="Toko Makmur")
    tid = await _tiket(pg, "TK-AUTO-02", barang=2_480, pembeli="Toko Lain")
    async with pg() as db:
        hasil = await bk.auto_tautkan(db, user=await db.get(User, gudang["adm"]))
    assert hasil.tertaut == []
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        assert rec.timbangan_transaksi_id is None
        assert rec.status == "dimuat"


async def test_auto_taut_melewati_tanggal_berbeda(pg, gudang):
    from datetime import timedelta

    from app.database import now_local
    from app.models import OutgoingRecord, User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=100)
    tid = await _tiket(pg, "TK-AUTO-03", barang=2_480,
                       tanggal=now_local().date() - timedelta(days=1))
    async with pg() as db:
        hasil = await bk.auto_tautkan(db, user=await db.get(User, gudang["adm"]))
    assert hasil.tertaut == []
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        assert rec.timbangan_transaksi_id is None


async def test_auto_taut_melewati_selisih_berat_di_luar_ambang(pg, gudang):
    """Selisih besar menuntut sebab tertulis manusia (`verifikasi` menolaknya
    tanpa itu) — auto-taut tidak mengarang sebab, cukup melewatkannya."""
    from app.models import OutgoingRecord, User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=100)         # 2.500 kg
    # Ambang untuk 2.500 kg = max(100, 2.500×2%) = 100 kg. 150 kg melewatinya.
    tid = await _tiket(pg, "TK-AUTO-04", barang=2_650)
    async with pg() as db:
        hasil = await bk.auto_tautkan(db, user=await db.get(User, gudang["adm"]))
    assert hasil.tertaut == []
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        assert rec.timbangan_transaksi_id is None


async def test_auto_taut_melewati_yang_ambigu(pg, gudang):
    """Satu tiket yang cocok dengan LEBIH DARI SATU pesanan — pembeli dan
    tanggal sama, berat sama-sama masuk ambang keduanya — dilewati, bukan
    ditautkan ke salah satunya. Falsafah yang sama dengan nama kembar di
    `hmu_core.kledo_kontak`: menebak berarti bisa salah pasang."""
    from app.models import OutgoingRecord, User
    from app.services import barang_keluar as bk

    a = await _sampai_dimuat(pg, gudang, karung=100)           # 2.500 kg
    b = await _sampai_dimuat(pg, gudang, karung=100, pembeli="Toko Makmur")
    tid = await _tiket(pg, "TK-AUTO-05", barang=2_480)         # cocok untuk keduanya
    async with pg() as db:
        hasil = await bk.auto_tautkan(db, user=await db.get(User, gudang["adm"]))
    assert hasil.tertaut == []
    assert len(hasil.dilewati) == 1
    assert "2 pesanan" in hasil.dilewati[0], hasil.dilewati[0]
    async with pg() as db:
        rec_a, rec_b = await db.get(OutgoingRecord, a), await db.get(OutgoingRecord, b)
        assert rec_a.timbangan_transaksi_id is None
        assert rec_b.timbangan_transaksi_id is None


async def test_auto_taut_tak_menyentuh_tiket_yang_sudah_tertaut(pg, gudang):
    from app.models import User
    from app.services import barang_keluar as bk

    rid = await _sampai_dimuat(pg, gudang, karung=100)
    tid = await _tiket(pg, "TK-AUTO-06", barang=2_480)
    async with pg() as db:
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=rid, timbangan_transaksi_id=tid)
    # Pesanan kedua, pembeli & berat sama — tanpa tiket keluar yang aktif
    # (yang tadi sudah tertaut), tak ada yang bisa ditautkan lagi ke sini.
    await _sampai_dimuat(pg, gudang, karung=100)
    async with pg() as db:
        hasil = await bk.auto_tautkan(db, user=await db.get(User, gudang["adm"]))
    assert hasil.tertaut == [], "tiket yang sudah tertaut ikut ditautkan ulang"


async def test_rute_auto_taut_keluar_dipanggil_dari_aksi(pg, gudang):
    from app.models import User
    from app.web import aksi_inventory as inv

    rid = await _sampai_dimuat(pg, gudang, karung=100)
    tid = await _tiket(pg, "TK-AUTO-07", barang=2_480)
    async with pg() as db:
        r = await inv.act_auto_taut_keluar(user=await db.get(User, gudang["adm"]))
    assert r["ok"] and "1 tertaut" in r["pesan"], r

    from app.models import OutgoingRecord
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        assert rec.timbangan_transaksi_id == tid


@pytest.mark.parametrize("dimuat", [False, True])
async def test_koreksi_plat_sebelum_verifikasi_tidak_mengubah_stok(pg, gudang, dimuat):
    from sqlalchemy import select
    from app.models import User, ActivityLog
    from app.services import barang_keluar as bk
    from app.web.layar_keluar import _tombol

    r = await _perintah(pg, gudang)
    async with pg() as db:
        adm = await db.get(User, gudang["adm"])
        if dimuat:
            await bk.muat_semua(db, user=await db.get(User, gudang["op"]), rec_id=r.rec.id)
        stok_lama = await _stok(pg, gudang)
        rec = await bk.koreksi_plat(db, user=adm, rec_id=r.rec.id,
                                  no_polisi=" h 9313 ic ", alasan="Salah ketik plat truk")
        assert rec.no_polisi == "H 9313 IC"
        assert await _stok(pg, gudang) == stok_lama
        assert "pilih_tiket_armada" in [t[0] for t in _tombol(rec, boleh_perintah=True, boleh_muat=False)]
        jejak = (await db.execute(select(ActivityLog).where(
            ActivityLog.aksi == "koreksi_plat_pengiriman"))).scalars().one()
        assert jejak.old_value == "B 1234 XY" and jejak.new_value == "H 9313 IC"
        assert jejak.alasan_perubahan == "Salah ketik plat truk"


@pytest.mark.parametrize("status,tautan", [("selesai", None), ("batal", None), ("dimuat", 299)])
async def test_koreksi_plat_menolak_pengiriman_final_atau_tertaut(pg, gudang, status, tautan):
    from app.models import User, OutgoingRecord
    from app.services import barang_keluar as bk
    r = await _perintah(pg, gudang)
    async with pg() as db:
        rec = await db.get(OutgoingRecord, r.rec.id)
        rec.status, rec.timbangan_transaksi_id = status, tautan
        await db.commit()
        with pytest.raises(bk.BarangKeluarError):
            await bk.koreksi_plat(db, user=await db.get(User, gudang["adm"]), rec_id=rec.id,
                                 no_polisi="H 9313 IC", alasan="Koreksi")
        assert rec.no_polisi == "B 1234 XY"


async def test_koreksi_plat_api_tidak_boleh_operator(pg, gudang):
    from fastapi import HTTPException
    from app.models import User
    from app.web.aksi_inventory import act_koreksi_plat_pengiriman, KoreksiPlatReq
    async with pg() as db:
        with pytest.raises(HTTPException) as e:
            await act_koreksi_plat_pengiriman(KoreksiPlatReq(perintah="1", no_polisi="H 9313 IC", alasan="Koreksi"),
                                              user=await db.get(User, gudang["op"]))
        assert e.value.status_code == 403


async def _armada_uji(pg, kode, pelanggan_id):
    from sqlalchemy import text
    tid=await _tiket(pg,kode)
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET pelanggan_id=:pid,status_tiket='TERBUKA',nomor_polisi='H 9313 IC',berat_barang_kg=NULL WHERE id=:id"),{'id':tid,'pid':pelanggan_id})
        await db.commit()
    return tid


async def test_perintah_sebelum_armada_tiket_dipilih_setelahnya(pg,gudang):
    from app.models import User,OutgoingRecord
    from app.services import barang_keluar as bk
    from app.web.aksi_inventory import tiket_armada
    from app.web.layar_keluar import _tombol
    from sqlalchemy import text
    r=await _perintah(pg,gudang)
    async with pg() as db:
        rec=await db.get(OutgoingRecord,r.rec.id)
        rec.no_polisi=None
        await db.commit()
        assert rec.timbangan_transaksi_id is None
        pid=rec.pelanggan_id
    tid=await _armada_uji(pg,'KLR-UJI-ARMADA',None)
    stok_lama=await _stok(pg,gudang)
    async with pg() as db:
        u=await db.get(User,gudang['adm'])
        pilihan=await tiket_armada(induk=str(r.rec.id),user=u)
        assert str(tid) in [x['value'] for x in pilihan]
        rec=await bk.pilih_tiket_armada(db,user=u,rec_id=r.rec.id,tiket_id=tid)
        assert rec.no_polisi=='H 9313 IC' and rec.timbangan_transaksi_id==tid
        identitas = (await db.execute(text(
            "SELECT pelanggan_id,pihak_nama FROM timbangan_transaksi WHERE id=:id"
        ), {"id": tid})).mappings().one()
        assert identitas["pelanggan_id"] == pid
        assert identitas["pihak_nama"] == rec.nama_pembeli
        assert 'pilih_tiket_armada' in [x[0] for x in _tombol(rec,boleh_perintah=True,boleh_muat=False)]
        from fastapi import HTTPException
        from app.web.internal import _cocokkan_pengiriman_tiket
        from app.web.aksi_inventory import timbang_keluar_aktif
        with pytest.raises(HTTPException) as e:
            await _cocokkan_pengiriman_tiket(db,tid)
        assert 'belum dinyatakan selesai' in e.value.detail
        await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=rec.id)
        _,cocok,_=await _cocokkan_pengiriman_tiket(db,tid)
        assert cocok.id==rec.id
        # Nama snapshot perintah boleh tertinggal setelah kontak diperbarui;
        # identitas pelanggan tetap ditentukan ID, bukan mengharuskan ketik ulang.
        await db.execute(text("UPDATE pelanggan SET nama_pelanggan='Nama kontak terbaru' WHERE id=:pid"), {'pid': pid})
        await db.commit()
        _, cocok, _ = await _cocokkan_pengiriman_tiket(db, tid)
        assert cocok.id == rec.id
        with pytest.raises(bk.BarangKeluarError,match='timbang kedua'):
            await bk.verifikasi(db,user=u,rec_id=rec.id)
        await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='SELESAI',berat_barang_kg=2500,netto_timbangan_kg=2500 WHERE id=:id"),{'id':tid})
        await db.commit()
        pilihan_verifikasi=await timbang_keluar_aktif(induk=str(rec.id),user=u)
        assert str(tid) in [x['value'] for x in pilihan_verifikasi]
        rec,_=await bk.verifikasi(db,user=u,rec_id=rec.id)
        assert rec.status=='selesai' and rec.timbangan_transaksi_id==tid
    assert await _stok(pg,gudang)==stok_lama-2500


async def test_armada_datang_dulu_plat_otomatis_dari_tiket(pg,gudang):
    from app.models import User
    from app.services import barang_keluar as bk
    pid=await _pelanggan(pg,'Toko Armada')
    tid=await _armada_uji(pg,'KLR-ARMADA-DULU',None)
    async with pg() as db:
        u=await db.get(User,gudang['adm'])
        r=await bk.buat_perintah(db,user=u,pelanggan_id=pid,tiket_armada_id=tid,
            no_polisi='PLAT MANUAL DIABAIKAN',baris=[bk.BarisPerintah(
                tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=10)])
        assert r.rec.no_polisi=='H 9313 IC' and r.rec.timbangan_transaksi_id==tid
        with pytest.raises(bk.BarangKeluarError,match='pengiriman lain'):
            await bk.buat_perintah(db,user=u,pelanggan_id=pid,tiket_armada_id=tid,
                baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=10)])


async def test_pilih_armada_menolak_pelanggan_lain(pg,gudang):
    from app.models import User
    from app.services import barang_keluar as bk
    r=await _perintah(pg,gudang)
    pid=await _pelanggan(pg,'Pelanggan Armada Berbeda')
    tid=await _armada_uji(pg,'KLR-ARMADA-BEDA',pid)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError,match='Pelanggan'):
            await bk.pilih_tiket_armada(db,user=await db.get(User,gudang['adm']),rec_id=r.rec.id,tiket_id=tid)


async def test_riwayat_barang_keluar_tabel_dan_detail_tiket(pg, gudang):
    from app.models import User
    from app.services import barang_keluar as bk
    from pathlib import Path

    aktif = await _perintah(pg, gudang, karung=10, pembeli="Pelanggan Aktif")
    rid = await _sampai_dimuat(pg, gudang, karung=100)
    tid = await _tiket(pg, "KLR-RIWAYAT", barang=2500)
    async with pg() as db:
        rec, _ = await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                                     rec_id=rid, timbangan_transaksi_id=tid)
        kode = rec.kode
    c = await _klien(pg, gudang["adm"], "uji_riwayat_detail")
    async with c:
        daftar = await c.get("/barang-keluar")
        detail = await c.get(f"/barang-keluar/{rid}")
        hilang = await c.get("/barang-keluar/9999999")
    assert daftar.status_code == detail.status_code == 200
    assert hilang.status_code == 404
    h = daftar.text
    sebelum, riwayat = h.split('<h2 id="judul-riwayat-keluar">', 1)
    assert aktif.rec.kode in sebelum
    assert kode not in sebelum
    assert '<table class="tabel-standar"' in riwayat
    assert f'href="/barang-keluar/{rid}"' in riwayat
    assert kode in riwayat and "KLR-RIWAYAT" in riwayat
    assert "KLR-RIWAYAT" in detail.text
    assert 'class="kirim-detail__tabel"' in detail.text
    assert "Dimuat aktual" in detail.text and "Sisa perintah" in detail.text
    assert "Riwayat petugas" in detail.text
    assert 'class="padat padat--' not in detail.text
    assert "Berat truk kosong" in detail.text and "Berat barang" in detail.text
    assert "buka=verifikasi_keluar" not in detail.text
    assert aktif.rec.kode not in detail.text
    Path("/tmp/hmu-keluar-daftar.html").write_text(h)
    Path("/tmp/hmu-keluar-detail.html").write_text(detail.text)


async def test_riwayat_paginasi_tidak_menghilangkan_perintah_aktif(pg, gudang):
    from app.database import now_local
    from app.models import OutgoingRecord

    aktif = await _perintah(pg, gudang, karung=10)
    async with pg() as db:
        for i in range(52):
            db.add(OutgoingRecord(kode=f"OUT-RIWAYAT-{i:03}", status="selesai",
                                 tanggal=now_local().date(), waktu=now_local(),
                                 waktu_perintah=now_local(), input_by=gudang["adm"]))
        await db.commit()
        from app.services import barang_keluar as bk
        terbaru = [r.id for r, _ in await bk.daftar(db, status=("selesai",), batas=100)]
    c = await _klien(pg, gudang["adm"], "uji_riwayat_paginasi")
    async with c:
        pertama = (await c.get("/barang-keluar")).text
        import re
        sebelum = re.search(r'/barang-keluar\?sebelum=(\d+)', pertama).group(1)
        kedua = (await c.get(f"/barang-keluar?sebelum={sebelum}")).text
        detail_lama = await c.get(f"/barang-keluar/{terbaru[-1]}")
    assert aktif.rec.kode in pertama and aktif.rec.kode in kedua
    assert pertama.count('data-detail-keluar=') == 50
    assert kedua.count('data-detail-keluar=') == 2
    assert "OUT-RIWAYAT-000" not in pertama
    assert "OUT-RIWAYAT-000" in kedua
    assert detail_lama.status_code == 200
    assert "Ditutup tanpa tiket timbang terkait" in detail_lama.text


async def test_borang_verifikasi_memakai_tiket_armada_tanpa_kode_ulang(pg, gudang):
    from app.web.aksi_inventory import spesifikasi
    aksi = next(x for x in spesifikasi(g2=True, fin=True) if x['id'] == 'verifikasi_keluar')
    assert [x['name'] for x in aksi['fields']] == ['perintah', 'sebab_selisih']
    assert 'dipakai otomatis' in aksi['hint']
    assert 'Timbang kedua harus selesai' in aksi['hint']


@pytest.mark.parametrize('merek,aktif', [('Pulenesia', True), ('Merek lama', False), (None, True)])
async def test_merek_muatan_sama_di_daftar_dan_detail(pg, gudang, merek, aktif):
    from sqlalchemy import select
    from app.penggilingan.inventory.models import Brand, ProductSku
    from app.web.layar_keluar import _nama_barang
    from app.services import barang_keluar as bk
    from pathlib import Path
    async with pg() as db:
        sku = await db.get(ProductSku, gudang['sku'])
        if merek:
            brand = await db.scalar(select(Brand).where(Brand.nama == merek))
            if brand is None:
                brand = Brand(nama=merek)
                db.add(brand)
            brand.aktif = aktif
            await db.flush()
            sku.brand_id = brand.id
        else:
            sku.brand_id = None
        await db.commit()
    r = await _perintah(pg, gudang, karung=10)
    stok_lama = await _stok(pg, gudang)
    async with pg() as db:
        baris = await bk.daftar(db, transaksi_id=r.rec.id)
        nama = await _nama_barang(db, baris)
        assert len(nama) == 1
        assert (merek or 'Tanpa merek') in next(iter(nama.values()))
    c = await _klien(pg, gudang['adm'], 'uji_merek_muatan')
    async with c:
        daftar = await c.get('/barang-keluar')
        detail = await c.get(f'/barang-keluar/{r.rec.id}')
    harapan = f"Beras Medium · {merek or 'Tanpa merek'} · Karung biasa 25\u00a0kg"
    assert harapan in daftar.text
    assert harapan in detail.text
    assert detail.text.count(harapan) == 1
    assert await _stok(pg, gudang) == stok_lama
    if merek == 'Pulenesia':
        Path('/tmp/keluar-merek-daftar.html').write_text(daftar.text)
        Path('/tmp/keluar-merek-detail.html').write_text(detail.text)


async def test_tombol_verifikasi_mendahului_rincian_timbang(pg, gudang):
    from pathlib import Path
    from app.models import OutgoingRecord
    rid = await _sampai_dimuat(pg, gudang, karung=100)
    tid = await _tiket(pg, 'KLR-UJI-TOMBOL-ATAS', barang=2500)
    async with pg() as db:
        rec = await db.get(OutgoingRecord, rid)
        rec.timbangan_transaksi_id = tid
        await db.commit()
    stok_lama = await _stok(pg, gudang)
    c = await _klien(pg, gudang['adm'], 'uji_tombol_atas')
    async with c:
        r = await c.get(f'/barang-keluar/{rid}')
    assert r.status_code == 200
    html = r.text
    assert html.index('Verifikasi &amp; tutup') < html.index('Rincian penimbangan')
    assert f'buka=verifikasi_keluar&nilai={rid}' in html
    assert 'KLR-UJI-TOMBOL-ATAS' in html
    assert await _stok(pg, gudang) == stok_lama
    async with pg() as db:
        assert (await db.get(OutgoingRecord, rid)).status == 'dimuat'
    Path('/tmp/verifikasi-utama-atas.html').write_text(html)


@pytest.mark.parametrize('jumlah', [80, 120])
async def test_detail_ubah_total_tidak_mengubah_aktual(pg, gudang, jumlah):
    from app.services import barang_keluar as bk
    from app.models import User
    rid = await _sampai_dimuat(pg, gudang, karung=100)
    stok = await _stok(pg, gudang)
    async with pg() as db:
        rec, items = (await bk.daftar(db, transaksi_id=rid))[0]
        dasar = (await bk.ringkasan_muat(db, rec))['dasar']
        await bk.ubah_baris_perintah(db, user=await db.get(User,gudang['adm']),
            rec_id=rid,item_id=items[0].id,dasar=dasar,jumlah=jumlah,alasan='Perubahan pesanan')
    async with pg() as db:
        rec, items = (await bk.daftar(db, transaksi_id=rid))[0]
        assert rec.status == 'perintah'
        assert items[0].jumlah_karung_perintah == jumlah
        assert items[0].jumlah_karung == 100
        assert float(items[0].berat_kg) == 2500
    assert await _stok(pg,gudang) == stok


@pytest.mark.parametrize('kasus', ['pecahan','stok','basi','hapus_dimuat','terakhir'])
async def test_detail_penjaga_ubah_item(pg,gudang,kasus):
    from app.services import barang_keluar as bk
    from app.models import User
    if kasus == 'hapus_dimuat':
        rid = await _sampai_dimuat(pg,gudang,karung=100)
    else:
        rid = (await _perintah(pg,gudang)).rec.id
    stok = await _stok(pg,gudang)
    async with pg() as db:
        rec, items = (await bk.daftar(db,transaksi_id=rid))[0]
        dasar = (await bk.ringkasan_muat(db,rec))['dasar']
        jumlah = {'pecahan':1.5,'stok':500}.get(kasus,80)
        if kasus == 'basi': dasar='lama'
        with pytest.raises(bk.BarangKeluarError):
            await bk.ubah_baris_perintah(db,user=await db.get(User,gudang['adm']),
                rec_id=rid,item_id=items[0].id,dasar=dasar,jumlah=jumlah,
                hapus=kasus in ('hapus_dimuat','terakhir'),alasan='Uji penjaga')
        await db.rollback()
    assert await _stok(pg,gudang) == stok


async def test_detail_hapus_item_belum_dimuat_dan_formulir_basi(pg,gudang):
    from app.services import barang_keluar as bk
    from app.models import User,OutgoingItem
    r=await _perintah(pg,gudang)
    async with pg() as db:
        rec,items=(await bk.daftar(db,transaksi_id=r.rec.id))[0]
        # Item kedua curah tidak mengurangi stok sebab aktualnya masih nol.
        it=OutgoingItem(outgoing_record_id=rec.id,item_type='byproduct_curah',
                        jenis_byproduct='menir',berat_perintah_kg=10,berat_kg=0)
        db.add(it);await db.commit()
        dasar=(await bk.ringkasan_muat(db,rec))['dasar'];iid=it.id
        await bk.ubah_baris_perintah(db,user=await db.get(User,gudang['adm']),
            rec_id=rec.id,item_id=iid,dasar=dasar,jumlah=None,hapus=True,alasan='Tidak jadi dikirim')
        assert await db.get(OutgoingItem,iid) is None
        with pytest.raises(bk.BarangKeluarError,match='berubah'):
            await bk.ubah_baris_perintah(db,user=await db.get(User,gudang['adm']),
                rec_id=rec.id,item_id=items[0].id,dasar=dasar,jumlah=80,alasan='Tab lama')
    c=await _klien(pg,gudang['adm'],'uji_detail_kelola')
    async with c:
        daftar=await c.get('/barang-keluar');detail=await c.get(f'/barang-keluar/{rec.id}')
        assert f'href="/barang-keluar/{rec.id}"' in daftar.text
        assert 'Ubah jumlah' not in daftar.text
        assert 'Ubah jumlah' in detail.text
        assert 'Hapus item' not in detail.text  # Barang terakhir memakai pembatalan perintah.
        assert f'/barang-keluar/{rec.id}?buka=pilih_tiket_armada' in detail.text
        from pathlib import Path
        Path('/tmp/detail-kelola.html').write_text(detail.text)


async def test_detail_ubah_dua_operator_hanya_satu_diterima(pg,gudang):
    import asyncio
    from app.models import User
    from app.services import barang_keluar as bk
    r=await _perintah(pg,gudang)
    async with pg() as db:
        rec,items=(await bk.daftar(db,transaksi_id=r.rec.id))[0]
        dasar=(await bk.ringkasan_muat(db,rec))['dasar'];iid=items[0].id
    async def ubah(n):
        async with pg() as db:
            try:
                await bk.ubah_baris_perintah(db,user=await db.get(User,gudang['adm']),
                    rec_id=r.rec.id,item_id=iid,dasar=dasar,jumlah=n,alasan='Dua tab')
                return True
            except bk.BarangKeluarError:
                await db.rollback();return False
    assert sorted(await asyncio.gather(ubah(80),ubah(120))) == [False,True]
    assert await _stok(pg,gudang)==10000


async def test_http_detail_ubah_tolak_pengiriman_ulang_dan_operator(pg,gudang):
    import json,re
    from pathlib import Path
    from app.web import csrf
    r=await _perintah(pg,gudang)
    c=await _klien(pg,gudang['adm'],'uji_http_detail_keluar')
    async with c:
        detail=await c.get(f'/barang-keluar/{r.rec.id}')
        token=re.search(r'name="formulir-sesi" content="([^"]+)"',detail.text).group(1)
        pilihan=(await c.get('/api/actions/item-perintah-ubah')).json()
        menu=(await c.get('/api/actions/menu')).json()
        Path('/tmp/detail-kelola.html').write_text(detail.text)
        Path('/tmp/detail-kelola-menu.json').write_text(json.dumps(menu))
        Path('/tmp/detail-kelola-pilihan.json').write_text(json.dumps(pilihan))
        payload=dict(baris=pilihan[0]['value'],jumlah=80,alasan='Pesanan berkurang')
        hasil=await c.post('/api/actions/ubah-item-perintah',json=payload,headers={csrf.NAMA_HEADER:token})
        assert hasil.status_code==200,hasil.text
        ulang=await c.post('/api/actions/ubah-item-perintah',json=payload,headers={csrf.NAMA_HEADER:token})
        assert ulang.status_code==400 and 'berubah' in ulang.text
        # Semua tambahan satu formulir harus atomik: baris kedua gagal,
        # baris pertama tidak boleh telanjur tersimpan.
        stok=f"{gudang['sku']}|{gudang['std']}"
        tambah=await c.post('/api/actions/tambah-barang-keluar',
            json=dict(perintah=str(r.rec.id),barang=[dict(pilih=stok,jumlah=10),dict(pilih=stok,jumlah=1000)]),
            headers={csrf.NAMA_HEADER:token})
        assert tambah.status_code==400,tambah.text
        from app.services import barang_keluar as bk
        async with pg() as db:
            _,items=(await bk.daftar(db,transaksi_id=r.rec.id))[0]
            assert items[0].jumlah_karung_perintah==80
    c=await _klien(pg,gudang['op'],'uji_http_detail_operator',mode='operator')
    async with c:
        h=await c.get(f'/barang-keluar/{r.rec.id}')
        token=re.search(r'name="formulir-sesi" content="([^"]+)"',h.text).group(1)
        gagal=await c.post('/api/actions/ubah-item-perintah',json=payload,headers={csrf.NAMA_HEADER:token})
        assert gagal.status_code==403
    assert await _stok(pg,gudang)==10000


async def test_detail_tambahan_jasa_memisahkan_pesanan_dan_pemilik(pg,gudang):
    from app.models import Jasa,Pelanggan,User
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.database import now_local
    from app.services import barang_keluar as bk
    from app.web.aksi_inventory import barang_tambahan_perintah
    async with pg() as db:
        pa=Pelanggan(nama_pelanggan='Pemilik A');pb=Pelanggan(nama_pelanggan='Pemilik B')
        db.add_all([pa,pb]);await db.flush()
        pesanan=[Jasa(kode=f'JAS-UJI-DETAIL-{i}',pelanggan_id=p.id,status='berjalan')
                 for i,p in enumerate([pa,pa,pb])]
        db.add_all(pesanan);await db.flush()
        ids=[j.id for j in pesanan];pid=pa.id
        for j in pesanan:
            db.add(FinishedGoodsStock(product_sku_id=gudang['sku'],rice_quality_standard_id=gudang['std'],
                source_type='retur',jumlah_karung=20,berat_total_kg=500,jasa_id=j.id,
                waktu=now_local(),input_by=gudang['op']))
        await db.commit()
        u=await db.get(User,gudang['adm'])
        r=await bk.buat_perintah(db,user=u,jasa_id=ids[0],pelanggan_id=pid,
            baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=5)])
        rid=r.rec.id
        opsi=await barang_tambahan_perintah(induk=str(rid),user=u)
        assert any(f'@{ids[1]}' in x['value'] for x in opsi)
        assert all(f'@{ids[2]}' not in x['value'] for x in opsi)
        hasil=await bk.tambah_baris(db,user=u,rec_id=rid,jasa_id=ids[1],
            baris=bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=6))
        assert hasil.rec.jasa_id is None
        assert {i.jasa_id for i in hasil.baris}==set(ids[:2])
        rec,items=(await bk.daftar(db,transaksi_id=rid))[0]
        dasar=(await bk.ringkasan_muat(db,rec))['dasar']
        await bk.ubah_baris_perintah(db,user=u,rec_id=rid,item_id=items[1].id,dasar=dasar,jumlah=8,alasan='Tambah pesanan kedua')
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError,match='bukan milik'):
            await bk.tambah_baris(db,user=await db.get(User,gudang['adm']),rec_id=rid,jasa_id=ids[2],
                baris=bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=1))
    assert await _stok(pg,gudang)==10000


@pytest.mark.parametrize('status',['perintah','dimuat','selesai'])
async def test_pilihan_armada_tidak_menawarkan_tiket_tertaut_termasuk_sendiri(pg,gudang,status):
    from app.models import User,OutgoingRecord
    from app.services import barang_keluar as bk
    from app.web.aksi_inventory import tiket_armada
    r=await _perintah(pg,gudang,pembeli='Pelanggan Armada')
    lain=await _perintah(pg,gudang,pembeli='Pelanggan Armada')
    tid=await _armada_uji(pg,'KLR-ARMADA-TERPAKAI',None)
    bebas=await _armada_uji(pg,'KLR-ARMADA-BEBAS',None)
    async with pg() as db:
        u=await db.get(User,gudang['adm'])
        perintah_lain=await db.get(OutgoingRecord,lain.rec.id)
        perintah_asal=await db.get(OutgoingRecord,r.rec.id)
        perintah_lain.pelanggan_id=perintah_asal.pelanggan_id
        await db.commit()
        await bk.pilih_tiket_armada(db,user=u,rec_id=r.rec.id,tiket_id=tid)
        rec=await db.get(OutgoingRecord,r.rec.id);rec.status=status;await db.commit()
        for induk in ['',str(r.rec.id),str(lain.rec.id)]:
            pilihan=await tiket_armada(induk=induk,user=u)
            assert str(tid) not in [x['value'] for x in pilihan]
            assert str(bebas) in [x['value'] for x in pilihan]
        with pytest.raises(bk.BarangKeluarError,match='sudah dipilih'):
            await bk.pilih_tiket_armada(db,user=u,rec_id=lain.rec.id,tiket_id=tid)
    assert await _stok(pg,gudang)==10000


@pytest.mark.parametrize('status',['perintah','dimuat'])
async def test_lepas_armada_membebaskan_tiket_tanpa_mengubah_muatan(pg,gudang,status):
    from sqlalchemy import text,select
    from app.models import User,OutgoingRecord,ActivityLog
    from app.services import barang_keluar as bk
    from app.web.aksi_inventory import tiket_armada,perintah_armada_tertaut
    from app.web.layar_keluar import _tombol
    rid=(await _perintah(pg,gudang)).rec.id if status=='perintah' else await _sampai_dimuat(pg,gudang)
    tid=await _armada_uji(pg,'KLR-LEPAS-UJI',None)
    stok=await _stok(pg,gudang)
    async with pg() as db:
        u=await db.get(User,gudang['adm'])
        rec=await bk.pilih_tiket_armada(db,user=u,rec_id=rid,tiket_id=tid)
        assert 'lepas_tiket_armada' in [t[0] for t in _tombol(rec,boleh_perintah=True,boleh_muat=False)]
        opsi=await perintah_armada_tertaut(user=u)
        assert any(o['value'].startswith(f'{rid}|{tid}|') for o in opsi)
        sebelum=dict((await db.execute(text('SELECT * FROM timbangan_transaksi WHERE id=:id'),{'id':tid})).mappings().one())
        _,items=(await bk.daftar(db,transaksi_id=rid))[0]
        aktual=[(i.id,float(i.berat_kg or 0),i.jumlah_karung) for i in items]
        await bk.lepas_tiket_armada(db,user=u,rec_id=rid,tiket_id=tid,alasan='Armada diganti')
        rec,items=(await bk.daftar(db,transaksi_id=rid))[0]
        assert rec.status==status and rec.timbangan_transaksi_id is None and rec.no_polisi is None
        assert aktual==[(i.id,float(i.berat_kg or 0),i.jumlah_karung) for i in items]
        sesudah=dict((await db.execute(text('SELECT * FROM timbangan_transaksi WHERE id=:id'),{'id':tid})).mappings().one())
        assert sesudah==sebelum
        assert str(tid) in [o['value'] for o in await tiket_armada(induk=str(rid),user=u)]
        audit=(await db.execute(select(ActivityLog).where(ActivityLog.aksi=='barang_keluar_lepas_tiket_armada'))).scalars().one()
        assert audit.changed_by==gudang['adm'] and audit.alasan_perubahan=='Armada diganti'
        assert 'lepas_tiket_armada' not in [t[0] for t in _tombol(rec,boleh_perintah=True,boleh_muat=False)]
        with pytest.raises(bk.BarangKeluarError,match='berubah|dilepas'):
            await bk.lepas_tiket_armada(db,user=u,rec_id=rid,tiket_id=tid,alasan='Ulang')
    assert await _stok(pg,gudang)==stok


async def test_lepas_armada_formulir_basi_dan_pengiriman_selesai_ditolak(pg,gudang):
    from app.models import User,OutgoingRecord
    from app.services import barang_keluar as bk
    from app.web.aksi_inventory import act_lepas_tiket_armada,LepasArmadaReq
    from fastapi import HTTPException
    r=await _perintah(pg,gudang)
    lama=await _armada_uji(pg,'KLR-LEPAS-LAMA',None);baru=await _armada_uji(pg,'KLR-LEPAS-BARU',None)
    async with pg() as db:
        u=await db.get(User,gudang['adm'])
        await bk.pilih_tiket_armada(db,user=u,rec_id=r.rec.id,tiket_id=lama)
        await bk.pilih_tiket_armada(db,user=u,rec_id=r.rec.id,tiket_id=baru)
        with pytest.raises(bk.BarangKeluarError,match='berubah'):
            await bk.lepas_tiket_armada(db,user=u,rec_id=r.rec.id,tiket_id=lama,alasan='Formulir lama')
        await db.rollback()
        rec=await db.get(OutgoingRecord,r.rec.id);assert rec.timbangan_transaksi_id==baru
        rec.status='selesai';await db.commit()
        with pytest.raises(bk.BarangKeluarError):
            await bk.lepas_tiket_armada(db,user=u,rec_id=r.rec.id,tiket_id=baru,alasan='Sudah tutup')
    async with pg() as db:
        with pytest.raises(HTTPException) as e:
            await act_lepas_tiket_armada(LepasArmadaReq(perintah=f'{r.rec.id}|{baru}',alasan='Operator'),user=await db.get(User,gudang['op']))
        assert e.value.status_code==403


async def test_tiket_setelah_dilepas_bisa_dipakai_perintah_lain_dan_dihapus(pg,gudang):
    from app.models import User,OutgoingRecord
    from app.services import barang_keluar as bk
    from sqlalchemy import text
    a=await _perintah(pg,gudang);b=await _perintah(pg,gudang)
    tid=await _armada_uji(pg,'KLR-LEPAS-PINDAH',None)
    async with pg() as db:
        u=await db.get(User,gudang['adm'])
        ra=await db.get(OutgoingRecord,a.rec.id);rb=await db.get(OutgoingRecord,b.rec.id)
        rb.pelanggan_id=ra.pelanggan_id;await db.commit()
        await bk.pilih_tiket_armada(db,user=u,rec_id=ra.id,tiket_id=tid)
        await bk.lepas_tiket_armada(db,user=u,rec_id=ra.id,tiket_id=tid,alasan='Pindah pengiriman')
        await bk.pilih_tiket_armada(db,user=u,rec_id=rb.id,tiket_id=tid)
        assert rb.timbangan_transaksi_id==tid
        await bk.lepas_tiket_armada(db,user=u,rec_id=rb.id,tiket_id=tid,alasan='Tiket salah')
        # Tiket uji saja: buktikan tidak ada lagi FK produksi yang menahan
        # penghapusan Pos Timbang setelah tautannya benar-benar dilepas.
        await db.execute(text('DELETE FROM timbangan_transaksi WHERE id=:id'),{'id':tid})
        await db.commit()
        assert (await db.execute(text('SELECT id FROM timbangan_transaksi WHERE id=:id'),{'id':tid})).first() is None
    assert await _stok(pg,gudang)==10000


async def test_http_lepas_armada_cuplikan_lama_ditolak_dan_sukses_dicatat(pg,gudang):
    import re
    from app.models import User,OutgoingRecord
    from app.services import barang_keluar as bk
    from app.web import csrf
    r=await _perintah(pg,gudang)
    tid=await _armada_uji(pg,'KLR-HTTP-LEPAS',None)
    async with pg() as db:
        await bk.pilih_tiket_armada(db,user=await db.get(User,gudang['adm']),rec_id=r.rec.id,tiket_id=tid)
    c=await _klien(pg,gudang['adm'],'uji_http_lepas_armada')
    async with c:
        h=await c.get(f'/barang-keluar/{r.rec.id}')
        assert 'Lepas tiket armada' in h.text
        token=re.search(r'name="formulir-sesi" content="([^"]+)"',h.text).group(1)
        opsi=(await c.get('/api/actions/perintah-armada-tertaut')).json()
        payload=dict(perintah=opsi[0]['value'],alasan='Ganti armada')
        menu=(await c.get('/api/actions/menu')).json()
        aksi=next(x for x in menu if x['id']=='lepas_tiket_armada')
        assert aksi['kartu'] and aksi['konfirmasi']['ya']=='Ya, lepas tiket'
        async with pg() as db:
            u=await db.get(User,gudang['adm'])
            await bk.lepas_tiket_armada(db,user=u,rec_id=r.rec.id,tiket_id=tid,alasan='Petugas lain')
            await bk.pilih_tiket_armada(db,user=u,rec_id=r.rec.id,tiket_id=tid)
        basi=await c.post('/api/actions/lepas-tiket-armada',json=payload,headers={csrf.NAMA_HEADER:token})
        assert basi.status_code==400 and 'berubah' in basi.text
        opsi=(await c.get('/api/actions/perintah-armada-tertaut')).json()
        payload['perintah']=opsi[0]['value']
        sukses=await c.post('/api/actions/lepas-tiket-armada',json=payload,headers={csrf.NAMA_HEADER:token})
        assert sukses.status_code==200,sukses.text
        assert 'Lepas tiket armada' not in (await c.get(f'/barang-keluar/{r.rec.id}')).text
    async with pg() as db:
        assert (await db.get(OutgoingRecord,r.rec.id)).timbangan_transaksi_id is None
    assert await _stok(pg,gudang)==10000
