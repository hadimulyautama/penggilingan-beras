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
