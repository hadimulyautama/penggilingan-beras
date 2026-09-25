"""Tujuan PK Gudang 2 jadi RUJUKAN SILO, bukan dua nama yang diketik — 24 Sep 2026.

`silo_a` dan `silo_b` bukan tulisan di layar; ia nilai yang TERSIMPAN di
`pk_gudang2_intakes.tujuan`, `internal_transfers.lokasi_tujuan`, dan dua tabel
proyeksi berikut CHECK-nya. Kosakata seperti itu tak bisa tumbuh: silo Gudang 2
ketiga tak punya kata, jadi ia ada di master, tampil di borang penyosohan, dan
tak bisa menerima satu kilogram pun. Operator yang membacanya akan mengira
aplikasinya rusak — dan ia tidak salah. Temuan QA 24 September.

MENAMBAH `silo_c` KE DAFTARNYA BUKAN JAWABAN: itu memindahkan masalahnya ke
silo keempat. Yang membuat Gudang 1 benar bukan daftar yang lebih panjang,
melainkan tak ada daftar sama sekali — nama silonya dibaca dari master, dan
yang disimpan penunjuknya. Itu yang ditiru di sini:

  · `tujuan` / `lokasi_tujuan` kini menyimpan JENIS tempatnya — `silo` atau
    `ditumpuk`; `ditumpuk` tetap nilai istimewanya, sebab lantai tak punya id;
  · silo MANA disimpan sebagai `silo_id`.

BARIS LAMA TIDAK DIUBAH KATANYA, dan itu disengaja. `silo_a`/`silo_b` tetap
sah dan tetap terbaca, sebab tak ada lagi pembaca yang menimbang kata itu:
stok disaring dengan `silo_id`, dan labelnya dibaca dari master. Menulis ulang
kata di baris lama berarti menulis ulang cermin dari peristiwa yang muatannya
tetap memuat kata lama — dua kebenaran untuk satu kejadian.

Yang ditambahkan di sini KOLOMNYA, untuk dua tabel yang belum punya
(`pk_gudang2_intakes` dan `proyeksi_pk_masuk_g2` sudah punya `silo_id` sejak
lahir). Isinya diturunkan dari kata lamanya, satu kali, di sini — bukan ditebak
pembacanya tiap kali dibaca.

Revision ID: 0057_tujuan_pk_g2_rujukan_silo
Revises: 0056_giling_beberapa_silo
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057_tujuan_pk_g2_rujukan_silo"
down_revision: Union[str, None] = "0056_giling_beberapa_silo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Kata lama → nama silo di master. Dipakai SEKALI, untuk mengisi kolom baru.
#: Sesudah migrasi ini tak ada lagi kode yang memetakan kata ke silo.
_LAMA = (("silo_a", "Silo A"), ("silo_b", "Silo B"))


def upgrade() -> None:
    for tabel in ("internal_transfers", "proyeksi_transfer_pk"):
        op.add_column(tabel, sa.Column("silo_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_internal_transfers_silo", "internal_transfers", "silos",
                          ["silo_id"], ["id"])
    op.create_index("ix_internal_transfers_silo", "internal_transfers", ["silo_id"])

    # ── Isi kolom barunya dari kata lamanya ──
    #
    # Silonya dicari di GUDANG 2 saja: "Silo A" ada di kedua gudang, dan
    # menaut transfer PK ke Silo A Gudang 1 akan membuat stok gudang yang
    # salah bertambah tanpa satu pun galat.
    for kata, nama in _LAMA:
        for tabel, kolom in (("internal_transfers", "lokasi_tujuan"),
                             ("proyeksi_transfer_pk", "lokasi_tujuan"),
                             ("pk_gudang2_intakes", "tujuan"),
                             ("proyeksi_pk_masuk_g2", "tujuan")):
            op.execute(sa.text(f"""
                UPDATE {tabel} t SET silo_id = s.id
                FROM silos s JOIN warehouses w ON w.id = s.warehouse_id
                WHERE t.{kolom} = :kata AND s.nama_silo = :nama
                  AND w.nama_gudang LIKE 'Gudang 2%'
                  AND t.silo_id IS NULL
            """).bindparams(kata=kata, nama=nama))

    # ── CHECK diperlebar, kata lamanya TETAP SAH ──
    #
    # Ia masih berdiri di baris lama, dan proyeksi bisa dibangun ulang dari
    # peristiwa yang muatannya memuat kata itu. CHECK yang menolaknya akan
    # membuat `bangun_ulang_proyeksi` gagal di tengah — pada data yang justru
    # tidak salah.
    for tabel, kolom, nama_ck in (
            ("proyeksi_pk_masuk_g2", "tujuan", "ck_proyeksi_pk_masuk_g2_tujuan"),
            ("proyeksi_transfer_pk", "lokasi_tujuan", "ck_proyeksi_transfer_pk_tujuan")):
        op.drop_constraint(nama_ck, tabel, type_="check")
        op.create_check_constraint(
            nama_ck, tabel,
            f"{kolom} IN ('silo', 'ditumpuk', 'silo_a', 'silo_b')")

    # Baris silo tanpa rujukan silo = baris yang tak bisa dijumlahkan ke silo
    # mana pun. Diperiksa, tidak diperbaiki diam-diam: yang tersisa di sini
    # berarti ada tujuan lain yang tak pernah diduga, dan itu keputusan orang.
    sisa = op.get_bind().execute(sa.text("""
        SELECT count(*) FROM pk_gudang2_intakes
        WHERE tujuan <> 'ditumpuk' AND silo_id IS NULL
    """)).scalar()
    if sisa:
        raise RuntimeError(
            f"{sisa} baris pk_gudang2_intakes bertujuan silo tetapi tanpa silo_id — "
            "periksa nilainya sebelum melanjutkan.")


def downgrade() -> None:
    # CHECK lama hanya bisa berdiri kembali bila tak ada baris bertujuan
    # `silo` — yaitu bila belum ada PK yang masuk sesudah perubahan ini. Kalau
    # ada, ia GAGAL di sini, dan itu benar: memaksa turun berarti memilih satu
    # silo untuk baris yang menunjuk silo lain.
    for tabel, kolom, nama_ck in (
            ("proyeksi_pk_masuk_g2", "tujuan", "ck_proyeksi_pk_masuk_g2_tujuan"),
            ("proyeksi_transfer_pk", "lokasi_tujuan", "ck_proyeksi_transfer_pk_tujuan")):
        op.drop_constraint(nama_ck, tabel, type_="check")
        op.create_check_constraint(
            nama_ck, tabel, f"{kolom} IN ('silo_a', 'silo_b', 'ditumpuk')")
    op.drop_index("ix_internal_transfers_silo", table_name="internal_transfers")
    op.drop_constraint("fk_internal_transfers_silo", "internal_transfers",
                       type_="foreignkey")
    for tabel in ("internal_transfers", "proyeksi_transfer_pk"):
        op.drop_column(tabel, "silo_id")
