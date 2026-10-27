"""Izin tampilan induk Pos Produksi, mengikuti peran dan gudang efektif.

Menu selalu memakai susunan Super Admin. Izin hanya menentukan kontrol yang
aktif; endpoint tetap memeriksa pelaku dan keadaan barang sebelum menulis.
Portal pelanggan mempunyai kontrak dan penyaring datanya sendiri.
"""
from hmu_identitas import peran as P


def hak(peran, *, g1=False, g2=False):
    admin = P.admin_keatas(peran)
    super_ = P.super_saja(peran)
    operator = P.operator_saja(peran)
    return dict(g1=admin or operator and g1, g2=admin or operator and g2,
                pengiriman=admin or operator and g2,
                admin=admin, super=super_, catat=admin or operator and (g1 or g2),
                fisik_g2=super_ or operator and g2,
                minta_pk=super_ or operator and g2)


def hak_view(view):
    peran = {P.V_SUPER: P.SUPERADMIN, P.V_ADMIN: P.ADMIN,
             P.V_SELEPAN: P.OPERATOR, P.V_POLESAN: P.OPERATOR}.get(view)
    return hak(peran, g1=view == P.V_SELEPAN, g2=view == P.V_POLESAN)


PINTU_HAK = {"barang_keluar": "pengiriman"}


PERAN_KOLOM = ((P.V_SUPER, "Super Admin"), (P.V_ADMIN, "Admin"),
               (P.V_SELEPAN, "Operator G1"), (P.V_POLESAN, "Operator G2"))


def matriks(akses):
    return [hak_view(view).get(akses, False) for view, _ in PERAN_KOLOM]


def daftar_umum():
    # Hak yang tidak berupa aksi katalog tetap dijelaskan di Pengaturan.
    return [dict(nama=nama, izin=matriks(kunci)) for nama, kunci in (
        ("Pekerjaan dan riwayat Gudang 1", "g1"),
        ("Pekerjaan dan riwayat Gudang 2", "g2"),
        ("Daftar Pengiriman", "pengiriman"),
        ("Laporan keuangan, koreksi, keputusan dan audit", "admin"),
        ("Kelola pengguna, akun, gudang dan alat", "super"),
        ("Ubah setelan kerja dan mutu", "admin"),
        ("Lihat sebagai peran lain", "admin"),
        ("Hapus data uji (bila mode uji aktif)", "super"),
        ("Minta lot PK Gudang 1", "minta_pk"),
        ("Pindah tumpukan dan masukkan bahan ke silo G2", "fisik_g2"),
    )] + [dict(nama="Kabar yang dapat dibaca", teks=[
        "Semua peran dan gudang", "Admin dan umum, semua gudang",
        "Operator dan umum, Gudang 1", "Operator dan umum, Gudang 2"])]
