"""Pengelompokan pintu laporan; tidak membaca atau menghitung transaksi."""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.web.security import butuh_akun

router = APIRouter(tags=["laporan"])
TAB = (("proses", "Proses"), ("qc", "QC"),
       ("laporan", "Laporan"), ("audit", "Audit"))
PROSES = (
    ("pengeringan", "Pengeringan", "/riwayat-pengeringan", "g1"),
    ("giling", "Penggilingan", "/riwayat-giling", "g1"),
    ("sosoh", "Penyosohan", "/riwayat-sosoh", "g2"),
    ("transfer", "Transfer", "/riwayat-transfer", "g1"),
)
QC = (
    ("gabah-basah", "Gabah basah", "/riwayat-qc/gabah-basah", "g1"),
    ("gabah-kering", "Gabah kering", "/riwayat-qc/gabah-kering", "g1"),
    ("pk-hasil-giling", "PK hasil giling", "/riwayat-qc/pk-hasil-giling", "g1"),
    ("pk-luar", "PK luar", "/riwayat-qc/pk-luar", "g2"),
    ("beras-hasil-sosoh", "Beras hasil sosoh", "/riwayat-qc/beras-hasil-sosoh", "g2"),
)


async def pilihan(akun):
    from app.web.portal.security import CustomerReader
    if isinstance(akun.user,CustomerReader):
        return {"laporan":[("laporan","Laporan","/laporan",None)],"proses":list(PROSES),"qc":list(QC),"audit":[("audit","Transfer kepemilikan","/audit",None)]}
    # Gerbang yang sama dengan halaman lama, memakai peran/gudang efektif.
    from app.web.api import _is_g1_operator, _is_g2_operator
    izin = {"g1": await _is_g1_operator(akun.user),
            "g2": await _is_g2_operator(akun.user)}
    return {"laporan": [("laporan", "Laporan", "/laporan", None)],
            "proses": [x for x in PROSES if izin[x[3]]],
            "qc": [x for x in QC if izin[x[3]]],
            "audit": [("audit", "Audit", "/audit", None)] if akun.is_admin else []}


def bagian(path):
    if path == "/laporan": return "laporan"
    if path == "/audit": return "audit"
    if path.startswith("/riwayat-qc/"): return "qc"
    if any(path == x[2] or path.startswith(x[2] + "/") for x in PROSES):
        return "proses"
    return None


async def siapkan(request: Request, konteks: dict):
    aktif = bagian(request.url.path)
    akun = getattr(request.state, "akun", None)
    if not aktif or not akun: return
    opsi = await pilihan(akun)
    judul = {"laporan": "Laporan", "proses": "Riwayat Proses",
             "qc": "Riwayat QC", "audit": "List audit"}
    jenis = next((x[0] for x in opsi[aktif] if request.url.path == x[2]
                  or request.url.path.startswith(x[2] + "/")), None)
    detail = any(request.url.path.startswith(x[2] + "/") for x in opsi[aktif])
    konteks["MENU_AKTIF"] = "laporan_riwayat"
    konteks["LAPORAN_NAV"] = {
        "aktif": aktif, "judul": judul[aktif], "jenis": jenis, "detail": detail,
        "tab": [{"kunci": k, "nama": n, "href": opsi[k][0][2]}
                for k, n in TAB if opsi[k]],
        "pilihan": opsi[aktif] if aktif in ("proses", "qc") else [],
    }


@router.get("/laporan-riwayat")
async def masuk(request: Request, tab: str | None = None, jenis: str = "",
                akun=Depends(butuh_akun)):
    """Pintu baru; URL lama tetap menjadi halaman sumber dan penjaga izin."""
    opsi = await pilihan(akun)
    if tab is None:
        tab = next(k for k, _ in TAB if opsi[k])
    if tab not in opsi: raise HTTPException(404, "Bagian tidak ditemukan.")
    if not opsi[tab]: raise HTTPException(403, "Bagian ini tidak tersedia untuk peran Anda.")
    tujuan = next((x[2] for x in opsi[tab] if x[0] == jenis), None)
    if jenis and tujuan is None:
        raise HTTPException(403, "Jenis riwayat ini tidak tersedia untuk peran Anda.")
    tujuan = tujuan or opsi[tab][0][2]
    # Rentang audit, kursor, notifikasi, dan parameter lama tidak dibuang.
    params = [(k, v) for k, v in request.query_params.multi_items()
              if k not in ("tab", "jenis")]
    return RedirectResponse(tujuan + ("?" + urlencode(params) if params else ""), status_code=303)
