"""Kerangka baca Riwayat proses; isi tetap handler native yang berizin."""
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

TUJUAN = {
    "riwayat-sosoh": dict(path="/riwayat-sosoh", jenis="penyosohan", title="Riwayat Penyosohan",
        columns=["Proses / selesai", "Nama pemilik", "Status jasa", "Bahan PK", "Beras", "Hasil samping", "Susut", "Rendemen", "Dijalankan"],
        captions=["Proses di halaman ini", "Bahan tercatat · kg", "Rata-rata rendemen"]),
    "riwayat-giling": dict(path="/riwayat-giling", jenis="penggilingan", title="Riwayat Penggilingan",
        columns=["Lot / selesai", "Pemilik", "Bahan", "Hasil PK", "Rendemen", "Kondisi", "Mutu"],
        captions=["Proses di halaman ini", "Bahan tercatat · kg", "PK tercatat · kg"]),
    "riwayat-pengeringan": dict(path="/riwayat-pengeringan", jenis="pengeringan", title="Riwayat Pengeringan",
        columns=["Lot / selesai", "Pemilik", "Dryer", "Status jasa", "Target KA", "Kadar air terakhir", "Bobot basah / kering", "Status silo"],
        captions=["Lot di halaman ini", "Bahan basah tercatat · kg", "Pengeringan dan pendinginan"]),
}


def memakai(request, kind):
    from app.web.portal.scope import is_customer_read
    return (kind in TUJUAN and not is_customer_read(request)
            and request.url.path == TUJUAN[kind]["path"]
            and not getattr(request.state, "isi_halaman_bertahap", False)
            and not getattr(request.state, "menyusun_kerangka_langsung", False)
            and (request.headers.get("X-Kerangka-Halaman") == "1"
                 or request.headers.get("X-Pindah") != "1"
                 and request.headers.get("Sec-Fetch-Mode") == "navigate"
                 and request.headers.get("Sec-Fetch-Dest") in {"document", "empty"}))


async def kerangka(request, akun, kind, *, navigasi=None):
    from app.web.api import _is_jenis_operator
    from app.web.halaman_bertahap import konteks_kerangka, penanda
    from app.web.laporan_navigasi import siapkan
    from app.web.tampilan import render
    config = TUJUAN[kind]
    if not await _is_jenis_operator(akun.user, config["jenis"]):
        raise HTTPException(403, "Riwayat ini tidak tersedia untuk gudang kerja Anda.")
    context = dict(await konteks_kerangka(request, akun) if navigasi is None else navigasi)
    await siapkan(request, context)
    context.update(layar=kind.replace("-", "_"), RIWAYAT=config,
        SHELL=dict(kind=kind, stamp=penanda(request, akun, kind),
                   data_url="/api/halaman-bertahap/"+kind+("?" + request.url.query if request.url.query else "")))
    response = render(request, "riwayat_bertahap.html", **context)
    # Hanya keluaran kerangka; Cetak native tetap aktif setelah isi tervalidasi.
    response.body = response.body.replace(b'data-lk-cetak',
        b'disabled aria-describedby="riwayat-baca-status" data-lk-cetak')
    if getattr(request.state, "frame_kerangka_langsung", False):
        from app.web.riwayat_kerangka_aset import paket_lokal
        response.body = paket_lokal(response.body, kind)
    response.headers["content-length"] = str(len(response.body))
    response.headers["Cache-Control"] = "private, no-store"
    return response


async def susun(request, akun, *, navigasi):
    from app.web.api import _is_jenis_operator
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.kerangka_langsung import kemas_frame
    from app.web.laporan_navigasi import masuk
    from app.web.security import NAMA_COOKIE, baca_token
    from app.web import csrf
    from hmu_tampilan import CAP_ASET
    state = {**request.scope.get("state", {}), "menyusun_kerangka_langsung": True, "frame_kerangka_langsung": True}
    frames = {}
    for kind, config in TUJUAN.items():
        if not await _is_jenis_operator(akun.user, config["jenis"]):
            continue
        path = config["path"]
        native = Request({**request.scope, "path":path, "raw_path":path.encode(), "query_string":b"", "state":dict(state)})
        response = await kerangka(native, akun, kind, navigasi=navigasi)
        if response.status_code != 200 or len(response.body) > 524288:
            return None
        frames[path] = response.body.decode()
    if not frames:
        return None
    # Alias mempertahankan keputusan server yang sebenarnya. Izin G1 pada
    # menu menggabungkan giling/pengeringan; itu bukan predicate setiap rute.
    alias = Request({**request.scope, "path":"/riwayat", "raw_path":b"/riwayat", "query_string":b"", "state":dict(state)})
    default = ""
    try:
        response = await masuk(alias, tab=None, jenis="", akun=akun)
        if isinstance(response, RedirectResponse) and response.headers.get("location") in frames:
            default = response.headers["location"]
    except HTTPException as error:
        if error.status_code not in (403,404):
            raise
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state,"csrf",None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request,akun),
        sesi=csrf.untuk_sesi(nonce,baca_token(request.cookies.get(NAMA_COOKIE)),request.cookies.get("produksi_lihat","")),
        default=default, **kemas_frame(frames))
    from jinja2.utils import htmlsafe_json_dumps
    if len(htmlsafe_json_dumps(result).encode()) > 1572864:
        return None
    return result
