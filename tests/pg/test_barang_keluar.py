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
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
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
    async with pg() as db:
        return await bk.buat_perintah(
            db, user=await db.get(User, g["adm"]),
            baris=[bk.BarisPerintah(tipe="finished_goods", sku_id=g["sku"],
                                    std_id=g["std"], jumlah_karung=karung)],
            nama_pembeli=pembeli, no_polisi="B 1234 XY")


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
                              rec_id=r.rec.id)
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
        (:kode, :tanggal, :arah, 'BERAS', 'DUA_KALI', 'Toko Makmur',
         'B 1234 XY', 5000, :waktu, :netto, :barang, 0, 'SELESAI', :st)
    RETURNING id
""")


async def _tiket(pg, kode, *, arah="KELUAR", barang=2_480, st="AKTIF"):
    from datetime import datetime, timezone

    from app.database import now_local
    async with pg() as db:
        tid = (await db.execute(_SQL_TIKET_KELUAR, {
            "kode": kode, "tanggal": now_local().date(), "arah": arah,
            "waktu": datetime.now(timezone.utc), "netto": barang + 20,
            "barang": barang, "st": st})).scalar_one()
        await db.commit()
        return tid


async def _sampai_dimuat(pg, g, karung=100):
    from app.models import User
    from app.services import barang_keluar as bk

    r = await _perintah(pg, g, karung=karung)
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

    tid = await _tiket(pg, "TK-002")
    a = await _sampai_dimuat(pg, gudang, karung=100)
    b = await _sampai_dimuat(pg, gudang, karung=40)
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

    async with pg() as db:
        r = await bk.buat_perintah(
            db, user=await db.get(User, gudang["adm"]),
            baris=[bk.BarisPerintah(tipe="pk_langsung", milling_process_id=pid,
                                    berat_kg=2_000)],
            nama_pembeli="Pabrik Seberang")
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
                nama_pembeli="Pabrik Seberang")
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

    async with pg() as db:
        u = await db.get(User, gudang["adm"])
        r = await inv.act_perintah_keluar(inv.PerintahKeluarReq(
            barang=[
                inv.BarisReq(pilih=f"bj:{gudang['sku']}|{gudang['std']}", jumlah=100),
                inv.BarisReq(pilih="pk:LOT-MULTI-01", jumlah=1_500),
            ],
            nama_pembeli="Toko Makmur", no_polisi="B 1234 XY"), user=u)
    assert r["ok"], r

    from app.services import barang_keluar as bk
    async with pg() as db:
        rec, items = (await bk.daftar(db))[0]
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

    async with pg() as db:
        u = await db.get(User, gudang["adm"])
        with pytest.raises(HTTPException) as e:
            await inv.act_perintah_keluar(inv.PerintahKeluarReq(
                barang=[
                    inv.BarisReq(pilih=f"bj:{gudang['sku']}|{gudang['std']}", jumlah=40),
                    inv.BarisReq(pilih=f"bj:{gudang['sku']}|{gudang['std']}"),
                ],
                nama_pembeli="Toko Makmur"), user=u)
    assert "jumlah" in str(e.value.detail).lower(), e.value.detail


async def test_bentuk_borang_lama_masih_diterima(pg, gudang):
    """Lembar yang sudah terbuka di layar orang saat versi baru terbit masih
    mengirim bentuk lama — satu barang, `stok` + `jumlah_karung`. Halaman di
    ponsel berumur panjang; yang berhenti cuma MENAWARKANNYA."""
    from app.models import User
    from app.web import aksi_inventory as inv

    async with pg() as db:
        u = await db.get(User, gudang["adm"])
        r = await inv.act_perintah_keluar(inv.PerintahKeluarReq(
            stok=f"{gudang['sku']}|{gudang['std']}", jumlah_karung=20,
            nama_pembeli="Toko Lama"), user=u)
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

    from app.models import ProduksiAkun, User
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
    async with pg() as db:
        await bk.tambah_baris(
            db, user=await db.get(User, gudang["adm"]), rec_id=baru.rec.id,
            baris=bk.BarisPerintah(tipe="finished_goods", sku_id=gudang["sku"],
                                   std_id=gudang["std"], jumlah_karung=20))
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
    # Dan jejak tiga langkahnya terbaca pada yang sudah tutup.
    assert "Diperintah" in h and "Dimuat" in h and "Diverifikasi" in h


async def test_operator_selepan_tak_ditawari_pintu_barang_keluar(pg, gudang):
    """Pintunya padam bersama Stok Produk, dan syaratnya SATU — dua syarat
    terpisah untuk alasan yang sama akan berbeda jawabannya kelak."""
    from app.models import User
    from app.services.berjalan import untuk

    async with pg() as db:
        u = await db.get(User, gudang["op"])
        u.default_warehouse_id = None          # bukan operator Gudang 2
        await db.commit()
        b = await untuk(db, u)
    mati = b.lencana()["PINTU_MATI"]
    assert ("barang_keluar" in mati) == ("stok_produk" in mati), \
        "kedua pintu berpisah nasib padahal sebabnya sama"


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
            nama_pembeli="Pabrik Seberang")

    async with pg() as db:
        g1 = await untuk_gudang1(db)
        g2 = await untuk_operator_gudang2(db)
    kode_g1 = {x.kode for x in g1.menunggu}
    kode_g2 = {x.kode for x in g2.menunggu}
    assert bb.rec.kode in kode_g1, "perintah PK tak sampai ke Gudang 1"
    assert a.rec.kode not in kode_g1, "perintah barang jadi bocor ke Gudang 1"
    assert a.rec.kode in kode_g2, "perintah barang jadi tak sampai ke Gudang 2"


async def test_admin_melihat_muatan_yang_menunggu_verifikasi_di_mejanya(pg, gudang):
    """Ia di MEJA, bukan di antrean: barangnya sudah di atas truk dan tak ada
    yang perlu diangkat lagi. Yang tertahan keputusan — apakah angkanya diakui
    apa adanya, dan tiket timbang mana yang ditempelkan."""
    from app.models import User
    from app.services import barang_keluar as bk
    from app.services.berjalan import untuk_staff

    r = await _perintah(pg, gudang, karung=100)
    baris = r.baris[0]
    async with pg() as db:
        await bk.catat_muatan(db, user=await db.get(User, gudang["op"]),
                              item_id=baris.id, jumlah_karung=80)
        await bk.selesai_muat(db, user=await db.get(User, gudang["op"]),
                              rec_id=r.rec.id)
    async with pg() as db:
        b = await untuk_staff(db)
    k = next((x for x in b.meja if x.kode == r.rec.kode), None)
    assert k is not None, "muatan tak berkartu di Menunggu keputusan"
    assert k.aksi == "verifikasi_keluar"
    # Selisihnya di RINGKASAN: yang memilih dari meja inilah yang memutuskan
    # mana yang perlu diperiksa lebih dulu.
    assert "kurang" in (k.ringkas or ""), k.ringkas
    assert "500" in (k.ringkas or ""), k.ringkas       # 2.500 − 2.000
    # Dan ia TIDAK ikut ke antrean: pekerjaan yang sama ditagih dua layar
    # membuat keduanya berhenti dipercaya.
    assert r.rec.kode not in {x.kode for x in b.menunggu}


async def test_tiket_keluar_terlewat_berkartu_diam_di_meja(pg, gudang):
    """Cerminan kartu "Tiket timbang belum dicatat" di sisi masuk.

    Tanpa ini, tiket keluar yang terlewat menghilang diam-diam: ia ditimbang di
    Pos Timbang lalu berhenti di situ, dan tak ada satu pun layar Produksi yang
    menyebutnya.

    DIAM — tanpa tombol. Jalan menautkannya lewat kartu verifikasi muatannya;
    menautkan tiket ke transaksi yang BELUM ada berarti mengarang muatannya.
    """
    from datetime import timedelta

    from app.database import now_local
    from app.services.berjalan import untuk_staff
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
        b = await untuk_staff(db)
    k = next((x for x in b.meja if x.kode == "TK-LEWAT-01"), None)
    assert k is not None, "tiket keluar yang terlewat tak berkartu"
    assert k.aksi is None, "kartunya bertombol — ia seharusnya DIAM"
    assert k.fase == "keluar", k.fase
    assert "Pos Timbang" in (k.nota or ""), k.nota


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
    from datetime import timedelta

    from app.database import now_local
    from app.models import User
    from app.services import barang_keluar as bk
    from app.services.berjalan import untuk_staff
    from sqlalchemy import text as _t

    tid = await _tiket(pg, "TK-TAUT-01")
    async with pg() as db:
        await db.execute(_t("UPDATE timbangan_transaksi SET tanggal = :t "
                            "WHERE id = :id"),
                         {"t": now_local().date() - timedelta(days=1), "id": tid})
        await db.commit()
    rid = await _sampai_dimuat(pg, gudang, karung=40)
    async with pg() as db:
        b = await untuk_staff(db)
    assert "TK-TAUT-01" in {x.kode for x in b.meja}, "belum tertaut, harus ditagih"

    async with pg() as db:
        await bk.verifikasi(db, user=await db.get(User, gudang["adm"]),
                            rec_id=rid, timbangan_transaksi_id=tid)
    async with pg() as db:
        b = await untuk_staff(db)
    assert "TK-TAUT-01" not in {x.kode for x in b.meja}, \
        "tiket yang sudah tertaut masih ditagih"
