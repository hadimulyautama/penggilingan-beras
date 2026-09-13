"""Pintu per aplikasi — siapa boleh masuk ke mana.

Keputusan pemilik 13 September 2026: operator → aplikasi operator (Gudang 2,
Pos Produksi); admin → Meja; timbangan → operator dan admin; superadmin →
semua aplikasi. Kantor AI: siapa pun di atas operator (aturan lama). Rincian
izin alat "akan disesuaikan" — belum di sini.

Pos Produksi masih menerima admin: hari ini admin masih mencatat di sana,
dan aturan "admin hanya ke Meja" baru bisa ditegakkan penuh setelah Meja
dipakai sungguhan. Saat itu tiba, yang diubah cukup satu baris di `BOLEH`.

Satu tabel, satu fungsi. Gerbang yang menyebut peran satu per satu (`peran
not in ("superadmin", "admin", "staff", "staf")` di Meja, QA M-06) adalah
gerbang yang tertinggal saat peran berubah.
"""
from __future__ import annotations

from . import peran as P

PRODUKSI, GUDANG2, MEJA, TIMBANGAN, KANTOR = "produksi", "gudang2", "meja", "timbangan", "kantor"
SEMUA_APLIKASI = (PRODUKSI, GUDANG2, MEJA, TIMBANGAN, KANTOR)

NAMA_APLIKASI = {PRODUKSI: "Pos Produksi", GUDANG2: "Operasi Gudang 2",
                 MEJA: "Meja Administrasi", TIMBANGAN: "Pos Timbang", KANTOR: "Kantor AI"}

#: Peran yang boleh masuk, per aplikasi. Super Admin ada di semuanya.
BOLEH: dict[str, tuple[str, ...]] = {
    PRODUKSI: (P.SUPERADMIN, P.ADMIN, *P.STAF_LAMA, P.OPERATOR),
    GUDANG2: (P.SUPERADMIN, P.OPERATOR),
    MEJA: (P.SUPERADMIN, P.ADMIN, *P.STAF_LAMA),
    TIMBANGAN: (P.SUPERADMIN, P.ADMIN, *P.STAF_LAMA, P.OPERATOR),
    KANTOR: (P.SUPERADMIN, P.ADMIN, *P.STAF_LAMA),
}

#: Operator di aplikasi ini wajib berlingkup gudang tertentu.
LINGKUP_OPERATOR = {GUDANG2: (P.G2,), PRODUKSI: (P.G1, P.G2)}


def sebab_tolak(peran: str | None, aplikasi: str, lingkup: str | None = None) -> str | None:
    """Alasan menolak, atau None bila boleh masuk.

    `lingkup` opsional: bila diberikan untuk operator, diperiksa terhadap
    gudang yang dilayani aplikasi. Tanpa lingkup (mis. pintu Meja yang belum
    tahu gudang), yang diperiksa hanya perannya.
    """
    p = P.normal(peran)
    nama = NAMA_APLIKASI.get(aplikasi, aplikasi)
    if aplikasi not in BOLEH or p not in BOLEH[aplikasi]:
        if P.operator_saja(p):
            return f"Akun operator tidak masuk lewat {nama} — pakai aplikasi operasi gudang Anda."
        if not p:
            return f"Akun ini belum punya peran; hubungi Super Admin."
        return f"Peran {P.LABEL.get(p, p)} tidak masuk lewat {nama}."
    if P.operator_saja(p) and lingkup is not None and aplikasi in LINGKUP_OPERATOR:
        if lingkup not in LINGKUP_OPERATOR[aplikasi]:
            gudang = " / ".join("Gudang 2" if g == P.G2 else "Gudang 1"
                                for g in LINGKUP_OPERATOR[aplikasi])
            return (f"Akun ini bukan operator {gudang} — pakai aplikasi gudang Anda sendiri."
                    if lingkup != P.TANPA else
                    "Akun operator ini belum diberi gudang; hubungi Super Admin.")
    return None


def boleh_masuk(peran: str | None, aplikasi: str, lingkup: str | None = None) -> bool:
    return sebab_tolak(peran, aplikasi, lingkup) is None
