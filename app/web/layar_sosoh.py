"""Layar Riwayat sosoh — ke mana perginya bahan baku tiap penyosohan.

Keputusan pemilik 2 Oktober 2026: *"berisi kartu proses sosoh yang selesai
berikut seluruh informasinya dan hasilnya. terkhusus berapa persen yang jadi
beras, berapa persen broken, berapa persen menir, berapa persen bekatul, lalu
berapa persen susut debu/bobot."*

Yang dijawabnya tak dijawab layar lain, dan itu sebabnya ia berdiri sendiri:

    /stok-produk   BERAPA yang ada sekarang — per kategori, seluruh riwayat
    /berjalan      proses yang MASIH menyala, angkanya belum final
    /laporan       apa yang terjadi HARI INI, seluruh pabrik
    halaman ini    satu proses = satu kartu, dan NERACANYA: 100% bahan baku
                   dibagi ke beras, samping, dan susut

Pertanyaan "berapa persen susut" tak bisa dijawab layar stok sama sekali: stok
menyebut apa yang ADA, sedangkan susut justru yang TIDAK ada — ia cuma terbaca
sebagai selisih antara yang masuk mesin dan yang keluar darinya.

HANYA YANG SELESAI. Proses berjalan sudah punya pintunya di `/berjalan`, dan
persen yang dihitung dari hasil yang masih bertambah akan dibaca sebagai hasil
akhir — lalu dipakai menilai mesin.
"""
from __future__ import annotations

from app.web.portal.scope import is_customer_read

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from app.database import SessionLocal
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter()

#: Sekali muat. Cukup besar untuk memuat sebulan penyosohan di pabrik ini,
#: cukup kecil untuk halaman yang dibuka di gudang lewat 4G.
SEKALI = 30


@router.get("/riwayat-sosoh")
async def halaman_riwayat_sosoh(request: Request, akun=Depends(butuh_akun)):
    """Kartu penyosohan selesai, terbaru lebih dulu, berikut neraca bobotnya."""
    from app.penggilingan.gudang2.polishing import SAMPING_DISEBUT, riwayat_sosoh
    from app.web.api import _is_g2_operator

    # ⚠ DIJAGA DI RUTENYA, bukan cuma di daftar pintu. Keputusan pemilik:
    # "hanya super admin, admin dan operator gudang 2 yang bisa lihat" —
    # dan `nav.TAB` hanya memilih pintu MANA YANG DITAWARKAN; alamatnya tetap
    # bisa diketik, dan halaman di ponsel berumur panjang.
    #
    # `_is_g2_operator` sudah berarti tepat ketiganya: admin ke atas selalu
    # boleh, operator hanya bila Gudang 2 yang SEDANG ia kerjakan (operator
    # tak terikat satu gudang — ia berpindah lewat "Kerja di gudang").
    # Menuliskan sendiri "superadmin atau admin atau operator g2" di sini
    # berarti menyebut peran harfiah, dan peran baru di puncak sudah sembilan
    # kali tertinggal di gerbang yang menyebut nama.
    if not await _is_g2_operator(akun.user):
        raise HTTPException(
            403, "Riwayat sosoh milik Admin ke atas dan operator Gudang 2.")

    sebelum = request.query_params.get("sebelum")
    try:
        sebelum_id = int(sebelum) if sebelum else None
    except ValueError:
        # Kursor ngawur diperlakukan sebagai "dari awal", bukan galat: ia
        # datang dari alamat yang diketik atau ditempel, dan halaman yang
        # menolak dengan 422 tak memberi jalan keluar kepada yang membacanya.
        sebelum_id = None

    async with SessionLocal() as db:
        kartu, lagi = await riwayat_sosoh(db, batas=SEKALI, sebelum=sebelum_id)
    return await render_laci(
        request, "riwayat_sosoh.html",
        kartu=kartu, lagi=lagi, SEKALI=SEKALI,
        SAMPING_DISEBUT=SAMPING_DISEBUT,
        # Kursor halaman berikutnya: id kartu TERAKHIR yang digambar.
        sesudah=(kartu[-1].id if kartu and lagi else None),
        # Halaman kedua dan seterusnya butuh jalan kembali — tanpa ini
        # satu-satunya jalan pulang adalah tombol kembali peramban, dan
        # `pindah.js` membuat riwayat peramban tak sejalan dengan halamannya.
        dari_awal=bool(sebelum_id),
    )


async def _pastikan_akses_sosoh(user):
    from app.web.api import _is_g2_operator
    if not await _is_g2_operator(user):
        raise HTTPException(403, "Laporan sosoh hanya untuk Admin ke atas dan operator Gudang 2.")


@router.get("/proses-sosoh/{kode_proses}")
async def detail_proses_sosoh(kode_proses: str, request: Request,
                              akun=Depends(butuh_akun)):
    """Tautan lama tetap membuka detail lengkap dengan tindakan di halaman ini."""
    from app.web.layar_berjalan import detail_proses_aktif
    return await detail_proses_aktif("sosoh", kode_proses, request, akun)


@router.get("/riwayat-sosoh/{process_id}")
async def detail_riwayat_sosoh(process_id: int, request: Request,
                               akun=Depends(butuh_akun)):
    if not is_customer_read(request):
        await _pastikan_akses_sosoh(akun.user)
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.penggilingan.gudang2.polishing import (
        _ALL_JENIS, alasan_koreksi_hasil, riwayat_sosoh,
    )
    from app.services.stok import nama_produk
    async with SessionLocal() as db:
        kartu, _ = await riwayat_sosoh(db, batas=1, process_id=process_id)
        output_logs = (await db.execute(
            select(PolishingOutputLog)
            .where(PolishingOutputLog.polishing_process_id == process_id)
            .order_by(PolishingOutputLog.id)
        )).scalars().all() if kartu and akun.is_admin else []
        hasil_awal = {jenis: 0.0 for jenis in _ALL_JENIS}
        for row in output_logs:
            if row.jenis in hasil_awal:
                hasil_awal[row.jenis] += float(row.berat_kg or 0)
        penghalang = (await alasan_koreksi_hasil(db, process_id)
                      if kartu and akun.is_admin else None)
    if not kartu:
        raise HTTPException(404, "Riwayat penyosohan tidak ditemukan.")
    from app.services.riwayat_jeda import riwayat_jeda
    async with SessionLocal() as db:
        jeda_riwayat = await riwayat_jeda(db, jenis="penyosohan", id_=process_id, params=request.query_params)
    from app.services.penghalang_koreksi import daftar
    async with SessionLocal() as db:
        catatan_penghalang = await daftar(db, "sosoh", process_id) if akun.is_admin and penghalang else []
    return await render_laci(
        request, "riwayat_detail.html", jenis="sosoh", k=kartu[0],
        catatan_penghalang=catatan_penghalang,
        kembali="/riwayat-sosoh", breadcrumb_detail=kartu[0].kode,
        layar="riwayat_sosoh",
        hasil_awal=hasil_awal,
        jenis_hasil=sorted(_ALL_JENIS),
        nama_hasil=nama_produk,
        boleh_koreksi=akun.is_admin,
        penghalang_koreksi=penghalang,
        hasil_koreksi=request.query_params.get("koreksi") == "berhasil",
        gagal_koreksi=getattr(request.state, "koreksi_gagal", None) or request.query_params.get("koreksi_gagal"),
        isian_koreksi=getattr(request.state, "koreksi_form", {}),
        jeda_riwayat=jeda_riwayat,
    )


@router.post("/riwayat-sosoh/{process_id}/koreksi")
async def koreksi_riwayat_sosoh(process_id: int, request: Request,
                                akun=Depends(butuh_akun)):
    """Koreksi hasil sosoh selesai dengan audit, tanpa tahap verifikasi."""
    if not akun.is_admin:
        raise HTTPException(403, "Koreksi hasil sosoh hanya untuk Admin ke atas.")
    from app.penggilingan.gudang2.polishing import (
        Gudang2Error, _ALL_JENIS, koreksi_hasil_sosoh,
    )
    form = await request.form()
    from app.web.layar_riwayat import _gagal_koreksi
    if form.get("wajib_periksa") and form.get("periksa_ulang") != "ya":
        return await _gagal_koreksi(request, akun, detail_riwayat_sosoh, process_id, form, "Periksa nilai terbaru terlebih dahulu.")
    perubahan: dict[str, float] = {}
    dasar: dict[str, float] = {}
    try:
        for key, value in form.multi_items():
            raw = str(value or "").strip().replace(",", ".")
            if key.startswith("hasil_"):
                jenis = key.removeprefix("hasil_")
                if jenis in _ALL_JENIS:
                    perubahan[jenis] = float(raw)
            elif key.startswith("dasar_"):
                jenis = key.removeprefix("dasar_")
                if jenis in _ALL_JENIS:
                    dasar[jenis] = float(raw)
    except (ValueError, TypeError):
        pesan_gagal = "Periksa berat hasil yang dimasukkan."
        return await _gagal_koreksi(request, akun, detail_riwayat_sosoh, process_id, form, pesan_gagal)
    alasan = str(form.get("alasan", "")).strip()
    async with SessionLocal() as db:
        try:
            await koreksi_hasil_sosoh(
                db, user=akun.user, process_id=process_id,
                perubahan=perubahan, dasar=dasar, alasan=alasan,
            )
        except Gudang2Error as e:
            await db.rollback()
            return await _gagal_koreksi(request, akun, detail_riwayat_sosoh, process_id, form, str(e))
    return RedirectResponse(
        f"/riwayat-sosoh/{process_id}?koreksi=berhasil", status_code=303)


@router.get("/riwayat-sosoh/{process_id}/laporan.pdf")
async def pdf_riwayat_sosoh(process_id: int, request: Request,
                            unduh: int = 0, akun=Depends(butuh_akun)):
    """PDF proses sosoh selesai, siap dibuka, diunduh, atau dibagikan."""
    await _pastikan_akses_sosoh(akun.user)
    return await laporan_sosoh_pdf(process_id, unduh)


async def laporan_sosoh_pdf(process_id: int, unduh: int = 0):
    """Shared PDF response; caller authorizes the process before invoking it."""
    from app.web.laporan_sosoh import ambil_data, buat_pdf
    data = await ambil_data(process_id)
    mode = "attachment" if unduh else "inline"
    filename = f"laporan-penyosohan-{data['process'].kode_proses}.pdf"
    return Response(
        content=buat_pdf(data), media_type="application/pdf",
        headers={"Content-Disposition": f'{mode}; filename="{filename}"',
                 "Cache-Control": "private, no-store"},
    )


@router.get("/riwayat-sosoh/{process_id}/laporan")
async def halaman_pdf_riwayat_sosoh(request: Request, process_id: int,
                                    akun=Depends(butuh_akun)):
    await _pastikan_akses_sosoh(akun.user)
    from app.penggilingan.gudang2.models import PolishingProcess
    async with SessionLocal() as db:
        process = await db.get(PolishingProcess, process_id)
    if process is None or process.status != "selesai":
        raise HTTPException(404, "Riwayat penyosohan tidak ditemukan.")
    return await render_laci(
        request, "laporan_sosoh.html",
        kode=process.kode_proses,
        pdf_url=f"/riwayat-sosoh/{process_id}/laporan.pdf",
    )
