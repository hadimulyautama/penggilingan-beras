"""Detail empat proses aktif: isi nyata, paginasi, akses dan perpindahan fase."""
from datetime import timedelta
from pathlib import Path
import os

import pytest
import pytest_asyncio

from tests.pg.test_qc_berjalan import giling, _catat
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_pengeringan import pabrik as dryer_pabrik, _batch_basah
from tests.pg.test_tambah_silo_berjalan import g1, _isi_silo_g1

pytestmark = pytest.mark.asyncio


def _potret(nama, response):
    if os.environ.get("UJI_POTRET_PROSES"):
        Path(f"/tmp/hmu-proses-{nama}.html").write_text(response.text)


@pytest_asyncio.fixture
async def pengeringan(pg, dryer_pabrik):
    from app.models import User
    from app.penggilingan.gudang1.services import drying as dr
    kode_batch = await _batch_basah(pg, dryer_pabrik, 8_000)
    async with pg() as db:
        u = await db.get(User, dryer_pabrik["user"])
        await dr.masuk_dryer(db, user=u, kode_batch_list=[kode_batch])
        r = await dr.start_drying(db, user=u, target_kadar_air=13.0)
        await dr.log_moisture(db, user=u, kode_lot=r.lot.kode_lot,
                              sampel=[18, 19, 17, 18], indikator=19)
        return {"kode": r.lot.kode_lot, "id": r.lot.id, "user": u.id, "batch": kode_batch}


@pytest.mark.parametrize("peran", ["operator", "admin", "superadmin"])
async def test_detail_pengeringan_bisa_dibuka_dari_daftar(pg, pengeringan, peran):
    kode = pengeringan["kode"]
    async with await _klien(pg, peran=peran, gudang="Gudang 1") as c:
        daftar = await c.get("/berjalan")
        r = await c.get(f"/proses-aktif/pengeringan/{kode}")
    assert r.status_code == 200
    assert f'/proses-aktif/pengeringan/{kode}' in daftar.text
    assert 'Kemajuan menuju target kadar air' in daftar.text
    for kata in [kode, pengeringan["batch"], "Riwayat pengukuran kadar air", "18,0%", "19,0%", "13%", "Durasi efektif", "kadar_air", "selesai_pengeringan"]:
        assert kata in r.text, kata
    _potret(f"pengeringan-{peran}", r)


async def test_fase_berubah_lalu_tautan_masuk_riwayat(pg, pengeringan):
    from app.models import User
    from app.penggilingan.gudang1.services import drying as dr
    kode = pengeringan["kode"]
    async with pg() as db:
        u = await db.get(User, pengeringan["user"])
        await dr.finish_drying(db, user=u, kode_lot=kode, kadar_air_akhir=13)
    async with await _klien(pg, peran="operator", gudang="Gudang 1") as c:
        r = await c.get(f"/proses-aktif/pengeringan/{kode}")
        assert r.status_code == 200 and r.url.path == f"/proses-aktif/pendinginan/{kode}"
        assert "Catatan pendinginan" in r.text and "selesai_pendinginan" in r.text
        _potret("pendinginan", r)
        async with pg() as db:
            await dr.finish_cooling(db, user=await db.get(User, pengeringan["user"]), kode_lot=kode)
        final = await c.get(f"/proses-aktif/pendinginan/{kode}")
    assert final.status_code == 200 and final.url.path == f"/riwayat-pengeringan/{pengeringan['id']}"


async def test_catatan_indikator_tidak_menghilangkan_ukur_alat_tes_terakhir(pg, pengeringan):
    from app.models import User
    from app.penggilingan.gudang1.services import drying as dr
    async with pg() as db:
        await dr.log_moisture(db, user=await db.get(User, pengeringan["user"]),
                              kode_lot=pengeringan["kode"], indikator=17)
    async with await _klien(pg, peran="operator", gudang="Gudang 1") as c:
        h = await c.get(f"/proses-aktif/pengeringan/{pengeringan['kode']}")
    assert h.status_code == 200
    ringkasan_alat = h.text.split("Kadar air terakhir · alat tes", 1)[1].split("</article>", 1)[0]
    assert "18,0%" in ringkasan_alat
    assert "Waktu ukur terakhir · alat tes" in h.text


async def test_giling_berulang_qc_lengkap_hasil_kumulatif_dan_paginasi(pg, giling):
    from app.database import now_local
    from app.models import MillingProgressLog
    for i in range(21):
        await _catat(pg, giling, kadar_air=14.4 if i < 20 else 16.5, broken=24, susut=12,
                     butir_kuning="bersih", gabah="sedikit", merang="sedang")
    async with pg() as db:
        db.add_all([MillingProgressLog(milling_process_id=giling["id"], berat_kumulatif_kg=kg,
                    waktu_update=now_local()+timedelta(seconds=i), input_by=giling["user"]) for i, kg in enumerate((100, 250))])
        await db.commit()
    async with await _klien(pg, peran="admin") as c:
        daftar = await c.get('/berjalan')
        r = await c.get(f"/proses-aktif/giling/{giling['kode']}")
        lebih = await c.get(f"/proses-aktif/giling/{giling['kode']}?halaman_qc=2")
    assert r.status_code == lebih.status_code == 200
    assert 'Rendemen sementara' in daftar.text
    assert 'Rendemen sementara PK terhadap gabah' in daftar.text
    for kata in ["250 kg", "Nilai kualitas QC PK", "Butir kuning", "Gabah", "Merang", "21 putaran", "QC 21", "qc_giling", "halaman_qc=2", "86,67", "B1"]:
        assert kata in r.text, kata
    assert "350 kg" not in r.text
    assert "QC 1 ·" not in r.text and "QC 1 ·" in lebih.text
    assert "21 putaran" in lebih.text  # rata-rata tidak bergantung halaman
    assert "86,67" in lebih.text
    _potret("giling-qc", r)


async def test_giling_dijeda_dan_sumber_semua_silo(pg, g1):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import start_milling
    from app.penggilingan.gudang1.services.jeda import hentikan
    await _isi_silo_g1(pg, g1, huruf="A", kode="GB-SUMBER-A", kg=3_000)
    await _isi_silo_g1(pg, g1, huruf="B", kode="GB-SUMBER-B", kg=2_000)
    async with pg() as db:
        u = await db.get(User, g1["user"])
        r = await start_milling(db, user=u, nama_silo=["A", "B"])
        await hentikan(db, user=u, jenis="giling", kode=r.proc.kode_proses, sebab="Listrik padam")
    async with await _klien(pg, peran="operator", gudang="Gudang 1") as c:
        h = await c.get(f"/proses-aktif/giling/{r.proc.kode_proses}")
    assert h.status_code == 200
    for kata in ["GB-SUMBER-A", "GB-SUMBER-B", "Silo A", "Silo B", "Dijeda", "Listrik padam", "lanjutkan_proses"]:
        assert kata in h.text
    assert "?buka=qc_giling" not in h.text
    _potret("giling-jeda", h)


async def test_sosoh_rinci_per_entri_jeda_dan_tautan_lama(pg, gudang2):
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, catat_output
    from app.penggilingan.gudang1.services.jeda import hentikan
    u = gudang2["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["B"])
        for kg in (100, 250):
            await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="medium", berat_kumulatif=kg, spek="UJI DETAIL")
        await hentikan(db, user=u, jenis="penyosohan", kode=r.proc.kode_proses, sebab="Listrik padam")
    async with await _klien(pg, peran="operator", gudang="Gudang 2") as c:
        daftar = await c.get('/berjalan')
        h = await c.get(f"/proses-aktif/sosoh/{r.proc.kode_proses}")
        lama = await c.get(f"/proses-sosoh/{r.proc.kode_proses}")
    assert h.status_code == lama.status_code == 200
    assert 'Neraca sementara: beras' in daftar.text
    assert 'belum dapat dihitung' not in daftar.text
    for kata in ["250 kg", "Bahan &amp; pemakaian silo", "UJI DETAIL", "Riwayat pencatatan hasil sosoh", "Pertambahan hasil", "total kumulatif per jenis hasil", "150 kg", "lanjutkan_penyosohan", "Listrik padam"]:
        assert kata in h.text, kata
    # Isian 100 lalu 250 adalah angka kumulatif; bukan 350 kg tambahan.
    assert "350 kg" not in h.text
    assert h.text.count("<h2>Bahan &amp; pemakaian silo</h2>") == 1
    assert "<h2>Pemakaian silo</h2>" not in h.text
    assert "<h2>Bahan baku masuk per silo</h2>" not in h.text
    _potret("sosoh", h)
    from app.penggilingan.gudang2.polishing import selesai_penyosohan, akhiri_penyosohan
    async with pg() as db:
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses, nama_silo="B", sisa_kg=0)
        assert r.proc.status == "proses"
        await akhiri_penyosohan(db, user=u, kode=r.proc.kode_proses)
    async with await _klien(pg, peran="superadmin") as c:
        selesai = await c.get(f"/proses-aktif/sosoh/{r.proc.kode_proses}", follow_redirects=False)
    assert selesai.status_code == 303 and selesai.headers["location"] == f"/riwayat-sosoh/{r.proc.id}"


async def test_akses_gudang_dan_alamat_tidak_sah(pg, giling):
    async with await _klien(pg, peran="operator", gudang="Gudang 2", lihat="operator:g2") as c:
        assert (await c.get(f"/proses-aktif/giling/{giling['kode']}")).status_code == 403
        assert (await c.get('/proses-aktif/aneh/XX')).status_code == 404
    async with await _klien(pg, peran="superadmin") as c:
        assert (await c.get('/proses-aktif/giling/TIDAK-ADA')).status_code == 404


async def test_qc_kosong_dan_giling_selesai_masuk_riwayat(pg, giling):
    from app.database import now_local
    from app.models import MillingProcess
    async with await _klien(pg, peran="operator", gudang="Gudang 1") as c:
        r = await c.get(f"/proses-aktif/giling/{giling['kode']}")
        assert r.status_code == 200
        assert "Belum dicatat" in r.text and "Belum dinilai" in r.text
        assert "?buka=qc_giling" not in r.text
        _potret("giling-kosong", r)
        async with pg() as db:
            p = await db.get(MillingProcess, giling["id"])
            p.status = "selesai"
            p.waktu_selesai = now_local()
            await db.commit()
        final = await c.get(f"/proses-aktif/giling/{giling['kode']}", follow_redirects=False)
        segar = await c.get(f"/proses-aktif/giling/{giling['kode']}", headers={"X-Pindah": "1"})
    assert final.status_code == 303 and final.headers['location'] == f"/riwayat-giling/{giling['id']}"
    assert segar.status_code == 200 and "window.location.replace" in segar.text
    assert f"/riwayat-giling/{giling['id']}" in segar.text
    _potret("peralihan-giling", segar)


async def test_detail_sosoh_memuat_asal_melebihi_batas_kartu(pg, gudang2):
    from datetime import date
    from sqlalchemy import select
    from app.database import now_local
    from app.models import Silo, Supplier, PkPurchaseBatch, PkGudang2Intake
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    u = gudang2["user"]
    async with pg() as db:
        silo = await db.scalar(select(Silo).where(Silo.nama_silo == "Silo B"))
        supplier = await db.scalar(select(Supplier.id))
        for i in range(1, 8):
            b = PkPurchaseBatch(kode_batch=f"PKB-DETAIL-{i}", supplier_id=supplier,
                berat_total_kg=100, tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                input_by=u.id, status_batch="diterima")
            db.add(b)
            await db.flush()
            db.add(PkGudang2Intake(sumber_tipe="pk_luar", pk_purchase_batch_id=b.id,
                tujuan="silo", silo_id=silo.id, berat_kg=100, tanggal_masuk=date.today(),
                waktu_masuk=now_local(), input_by=u.id))
        await db.commit()
        r = await mulai_penyosohan(db, user=u, nama_silos=["B"])
    async with await _klien(pg, peran="operator", gudang="Gudang 2") as c:
        h = await c.get(f"/proses-aktif/sosoh/{r.proc.kode_proses}")
    assert h.status_code == 200
    assert all(f"PKB-DETAIL-{i}" in h.text for i in range(1, 8))
    assert "baris lagi tak ditampilkan" not in h.text


async def test_bahan_jasa_tetap_menyebut_pemilik_di_detail(pg, g1):
    from app.models import Jasa, Pelanggan, User
    from app.penggilingan.gudang1.services.milling import start_milling
    async with pg() as db:
        pemilik = Pelanggan(nama_pelanggan="Ibu Dewi Titipan")
        db.add(pemilik)
        await db.flush()
        jasa = Jasa(kode="JAS-DETAIL-01", pelanggan_id=pemilik.id, status="berjalan")
        db.add(jasa)
        await db.commit()
    await _isi_silo_g1(pg, g1, huruf="A", kode="GB-JASA-DETAIL", kg=3_000, jasa_id=jasa.id)
    async with pg() as db:
        r = await start_milling(db, user=await db.get(User, g1["user"]), nama_silo="A")
    async with await _klien(pg, peran="operator", gudang="Gudang 1") as c:
        h = await c.get(f"/proses-aktif/giling/{r.proc.kode_proses}")
    assert h.status_code == 200 and "Ibu Dewi Titipan" in h.text
    assert "JAS-DETAIL-01" in h.text and "GB-JASA-DETAIL" in h.text
    _potret("giling-jasa", h)


async def test_silo_dilepas_diisi_ulang_tidak_mengganti_asal_proses(pg, gudang2):
    from sqlalchemy import select
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, catat_output, selesai_penyosohan
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
    u = gudang2["user"]
    async with pg() as db:
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=gudang2["intake_tumpukan"], nama_silo="A", berat=4_000)
        r = await mulai_penyosohan(db, user=u, nama_silos=["A", "B"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="medium", berat_kumulatif=1)
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses, nama_silo="A", sisa_kg=0)
        # Isi ulang dari batch berbeda; isi baru tidak boleh menjadi asal A
        # pada proses yang masih memakai B.
        from app.models import PkGudang2Intake, PkPurchaseBatch
        from app.database import now_local
        from datetime import date
        from app.models import Silo, Supplier
        b = PkPurchaseBatch(kode_batch="PKB-ISIAN-BARU", supplier_id=await db.scalar(select(Supplier.id)),
            berat_total_kg=600, tanggal_pembelian=date.today(), waktu_pembelian=now_local(), input_by=u.id, status_batch="diterima")
        db.add(b)
        await db.flush()
        sid = await db.scalar(select(Silo.id).where(Silo.nama_silo == "Silo A"))
        db.add(PkGudang2Intake(sumber_tipe="pk_luar", pk_purchase_batch_id=b.id,
            tujuan="silo", silo_id=sid, berat_kg=600, tanggal_masuk=date.today(), waktu_masuk=now_local(), input_by=u.id))
        await db.commit()
    async with await _klien(pg, peran="operator", gudang="Gudang 2") as c:
        h = await c.get(f"/proses-aktif/sosoh/{r.proc.kode_proses}")
    assert h.status_code == 200
    assert "PKB-20260912-01" in h.text and "PKB-20260912-02" in h.text
    assert "PKB-ISIAN-BARU" not in h.text
    assert "Dilepaskan" in h.text
