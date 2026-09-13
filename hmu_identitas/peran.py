"""Tangga peran, lingkup gudang, dan view — SATU tempat untuk lima repo.

Tangganya: operator < admin < superadmin. `staff`/`staf` adalah nama LAMA
yang masih ada di baris `users` sejak konsolidasi 3 September 2026; dibaca
sebagai admin, tak pernah ditawarkan lagi.

Peran TIDAK PERNAH disebut harfiah di kode aplikasi — pakai himpunan dan
fungsi di sini. Di produksi pola "gerbang menyebut nama satu per satu" sudah
sembilan kali memakan korban (peran baru di puncak tak dikenal gerbang lama);
uji AST di tiap repo (`penjaga.peran_harfiah`) menolaknya.
"""
from __future__ import annotations

OPERATOR = "operator"
ADMIN = "admin"
SUPERADMIN = "superadmin"

#: Nama lama yang masih sah dibaca (tak ditawarkan).
STAF_LAMA = ("staff", "staf")

#: Yang boleh dipilih saat mengelola akun, dari terendah.
PILIHAN = (
    (OPERATOR, "Mencatat pekerjaan di gudangnya atau di pos timbang. Tidak melihat angka uang."),
    (ADMIN, "Seluruh pencatatan, verifikasi harga, dan laporan uang."),
    (SUPERADMIN, "Semua di atas, ditambah mengelola orang, akun, dan alat. Tingkat tertinggi."),
)
PERAN_SAH = tuple(k for k, _ in PILIHAN)

LABEL = {OPERATOR: "Operator", ADMIN: "Admin", SUPERADMIN: "Super Admin",
         "staff": "Staff (lama)", "staf": "Staf (lama)"}

#: Tinggi tiap peran; yang tak dikenal = 0.
TINGKAT = {OPERATOR: 1, "staff": 2, "staf": 2, ADMIN: 3, SUPERADMIN: 4}

PERAN_ADMIN_KEATAS = (SUPERADMIN, ADMIN)
PERAN_STAF_KEATAS = (SUPERADMIN, ADMIN, *STAF_LAMA)
#: Boleh melihat angka uang. Sama isinya dengan staf ke atas — disebut
#: terpisah supaya bila kelak ada peran yang bekerja tanpa melihat harga,
#: yang berubah cukup satu.
PERAN_UANG = PERAN_STAF_KEATAS


def normal(peran: str | None) -> str:
    """Tahan spasi dan huruf besar: ' SuperAdmin ' → 'superadmin'."""
    return (peran or "").strip().lower()


def tingkat(peran: str | None) -> int:
    return TINGKAT.get(normal(peran), 0)


def admin_keatas(peran: str | None) -> bool:
    return normal(peran) in PERAN_ADMIN_KEATAS


def staf_keatas(peran: str | None) -> bool:
    """Siapa pun DI ATAS operator — termasuk nama lama."""
    return normal(peran) in PERAN_STAF_KEATAS


def super_saja(peran: str | None) -> bool:
    return normal(peran) == SUPERADMIN


def operator_saja(peran: str | None) -> bool:
    return normal(peran) == OPERATOR


def sah(peran: str | None) -> bool:
    """Boleh DITETAPKAN (bukan sekadar dibaca): nama lama tidak."""
    return normal(peran) in PERAN_SAH


def terlalu_tinggi(peran_pelaku: str | None, peran_sasaran: str | None) -> bool:
    """Sasaran lebih tinggi daripada pelaku? — langit-langit peran (QA P-S-10).

    Tak seorang pun mengangkat orang lebih tinggi dari dirinya sendiri, juga
    saat jaring pengaman "belum ada Super Admin → Admin diterima" terbentang.
    """
    return tingkat(peran_sasaran) > tingkat(peran_pelaku)


# ───────────────────────── Lingkup gudang ─────────────────────────

SEMUA, G1, G2, TANPA = "semua", "g1", "g2", "tanpa"

#: Awalan nama gudang di master `warehouses` → kode lingkup.
AWALAN_GUDANG = (("Gudang 1", G1), ("Gudang 2", G2))


def lingkup(peran: str | None, nama_gudang: str | None) -> str:
    """Lingkup kerja orang ini.

    Admin ke atas (dan nama lama) melihat dan mengerjakan semua gudang.
    Operator melekat pada SATU gudang — `users.default_warehouse_id` — dan
    operator tanpa gudang tak berhak apa-apa (`TANPA`): keadaan yang harus
    terbaca sebagai kesalahan pendaftaran, bukan layar kosong.
    """
    if staf_keatas(peran):
        return SEMUA
    if not operator_saja(peran):
        return TANPA
    nama = (nama_gudang or "").strip()
    for awalan, kode in AWALAN_GUDANG:
        if nama.startswith(awalan):
            return kode
    return TANPA


# ───────────────────────── View (tampilan) ─────────────────────────

V_SUPER, V_ADMIN, V_SELEPAN, V_POLESAN, V_TAMU = "super", "admin", "selepan", "polesan", "tamu"

NAMA_VIEW = {V_SUPER: "Super Admin", V_ADMIN: "Admin",
             V_SELEPAN: "Operator selepan", V_POLESAN: "Operator polesan",
             V_TAMU: "Belum punya gudang"}

#: Peran tersimpan → view, untuk yang tak bergantung gudang.
VIEW_DARI_PERAN = {SUPERADMIN: V_SUPER, ADMIN: V_ADMIN,
                   **{lama: V_ADMIN for lama in STAF_LAMA}}

#: View yang memegang kedua gudang sekaligus — dan karena itu melihat uang.
VIEW_MEJA = (V_SUPER, V_ADMIN)


def view(peran: str | None, lingkup_: str) -> str:
    """View dari peran EFEKTIF dan lingkupnya. Ini soal tampilan, bukan
    wewenang — gerbang yang menolak sungguhan tetap di rutenya."""
    p = normal(peran)
    if p in VIEW_DARI_PERAN:
        return VIEW_DARI_PERAN[p]
    if p == OPERATOR:
        return {G1: V_SELEPAN, G2: V_POLESAN}.get(lingkup_, V_TAMU)
    return V_TAMU


# ───────────────────────── Lihat sebagai ─────────────────────────

def urai(diminta: str | None) -> tuple[str, str | None]:
    """'operator:g1' → ('operator', 'g1'); gudang yang tak dikenal → None."""
    d = normal(diminta)
    if ":" in d:
        p, _, gd = d.partition(":")
        return p, (gd if gd in (G1, G2) else None)
    return d, None


def peran_efektif(asli: str | None, diminta: str | None) -> str:
    """Peran yang dipakai tampilan — tak pernah lebih tinggi dari yang asli."""
    a = normal(asli)
    d, _ = urai(diminta)
    if not d or d not in TINGKAT:
        return a
    if TINGKAT[d] > tingkat(a):
        return a
    return d


def boleh_menyamar(asli: str | None) -> bool:
    return tingkat(asli) >= TINGKAT[ADMIN]


# ───────────────────────── Timbangan (nama lama) ─────────────────────────

#: Pos timbang menyimpan perannya dengan nama sendiri: PETUGAS / ADMIN /
#: SUPERADMIN. Sejak identitas bersama, kolom itu hanya CERMIN dari
#: `users.role` — disinkronkan saat masuk — dan pemetaannya ada di sini.
KE_TIMBANGAN = {OPERATOR: "PETUGAS", ADMIN: "ADMIN", SUPERADMIN: "SUPERADMIN",
                **{lama: "ADMIN" for lama in STAF_LAMA}}
DARI_TIMBANGAN = {"PETUGAS": OPERATOR, "ADMIN": ADMIN, "SUPERADMIN": SUPERADMIN}


def ke_timbangan(peran: str | None) -> str:
    return KE_TIMBANGAN.get(normal(peran), "PETUGAS")


def dari_timbangan(role: str | None) -> str:
    return DARI_TIMBANGAN.get((role or "").strip().upper(), OPERATOR)
