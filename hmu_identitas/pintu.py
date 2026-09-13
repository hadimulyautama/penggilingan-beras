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

#: Gudang yang dilayani aplikasi — hanya untuk PESAN, bukan pagar. Operator
#: boleh masuk aplikasi operator mana pun (keputusan pemilik 13 Sep 2026:
#: operator saling menggantikan); di dalamnya ia bekerja sebagai operator
#: gudang yang dilayani aplikasi itu.
GUDANG_APLIKASI = {GUDANG2: (P.G2,), PRODUKSI: (P.G1, P.G2)}


def sebab_tolak(peran: str | None, aplikasi: str, lingkup: str | None = None) -> str | None:
    """Alasan menolak, atau None bila boleh masuk.

    `lingkup` (gudang utama operator) DITERIMA tetapi tak lagi menjadi pagar:
    operator boleh masuk aplikasi operator mana pun dan bekerja di gudang
    yang dilayani aplikasi itu. Parameternya dipertahankan untuk pemanggil
    lama dan untuk pesan.
    """
    p = P.normal(peran)
    nama = NAMA_APLIKASI.get(aplikasi, aplikasi)
    if aplikasi not in BOLEH or p not in BOLEH[aplikasi]:
        if P.operator_saja(p):
            return f"Akun operator tidak masuk lewat {nama} — pakai aplikasi operasi gudang Anda."
        if not p:
            return f"Akun ini belum punya peran; hubungi Super Admin."
        return f"Peran {P.LABEL.get(p, p)} tidak masuk lewat {nama}."
    return None


def boleh_masuk(peran: str | None, aplikasi: str, lingkup: str | None = None) -> bool:
    return sebab_tolak(peran, aplikasi, lingkup) is None
