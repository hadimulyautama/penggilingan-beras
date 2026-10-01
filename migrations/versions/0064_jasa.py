"""Jasa (toll milling) — irisan pertama: pemiliknya, bukan pembelinya.

Sampai hari ini setiap kilogram yang masuk pabrik ini DIBELI. `purchase_batches.
supplier_id` NOT NULL menuliskan anggapan itu di tingkat basis data, dan seluruh
layar stok berdiri di atasnya: apa yang ada di gudang adalah apa yang pabrik
punya.

Jasa membatalkan anggapan itu untuk sebagian baris. Gabah pelanggan dititipkan,
digiling, dan kembali — ia tak pernah dibeli dan tak pernah jadi stok pabrik.

**NULL = milik pabrik.** Kolom `jasa_id` yang kosong di seluruh baris lama sudah
benar sejak detik pertama, jadi tak ada backfill dan tak ada nilai bawaan selain
NULL. Satu pun perilaku hari ini tidak berubah oleh migrasi ini.

TANPA `kedalaman`. Sampai mana sebuah pesanan diproses bukan fakta yang
dinyatakan di muka melainkan hasil yang terbaca dari di mana barangnya berada
sekarang — keputusan pemilik 1 Oktober 2026: *"jika hanya jadi pk dan pk
ternyata keluar berarti hanya sampai pk."* Kolom yang menyimpannya adalah kolom
yang cepat atau lambat berselisih dengan kenyataannya.

TANPA kolom harga, tarif, atau total. Keputusan pemilik: *"biaya adalah urusan
keuangan. app timbangan dan operasional tidak mengurusi keuangan."* Kledo yang
menagih; di sini hanya BOBOT, TEMPAT, dan MILIK.

`hasil_ditahan` adalah CUPLIKAN kesepakatan saat pesanan dibuat, bukan pembacaan
kebijakan yang sedang berlaku. Kalau kebijakannya dibaca dari kode, mengubahnya
suatu hari akan mengubah arti SELURUH pesanan lama — termasuk yang notanya sudah
dipegang pelanggan. Pola yang sama sudah dipakai `MillingProcessSource.berat_kg`
dan `timbangan_transaksi.aturan_snapshot`, dengan alasan yang sudah tertulis di
sana.

── ENAM TABEL, bukan empat ──

Rancangan awal irisan ini membawa `jasa_id` ke empat tabel saja (gabah → PK di
Gudang 1) dan menghentikan jasa di situ. Pemilik memilih sebaliknya pada 1
Oktober 2026: `internal_transfers` dan `pk_gudang2_intakes` ikut sekarang, supaya
PK pelanggan yang dipindah ke Gudang 2 tidak kehilangan pemiliknya di perbatasan.

Itu menutup lubang yang paling berbahaya di antara dua irisan — PK pelanggan yang
berubah jadi PK pabrik tanpa satu pun galat — dan MEMINDAHKAN garis berhentinya ke
penyosohan: `polishing_process` masih tanpa pemilik, jadi `mulai_penyosohan`
MENOLAK silo yang berisi PK jasa sampai irisan Gudang 2 datang. Penolakan itu
dicabut di irisan berikutnya, bukan dirawat.

── `supplier_id` BOLEH NULL, dan CHECK yang menggantikannya ──

`CHECK ((supplier_id IS NOT NULL) <> (jasa_id IS NOT NULL))` — tepat satu terisi:
barang DIBELI, atau barang DITITIPKAN. Tidak keduanya, tidak nol-duanya.

⚠ Jalan pintas yang sengaja TIDAK diambil: memasukkan pelanggan ke tabel
`suppliers`. Supplier palsu akan ikut ke `timbangan_skor_supplier`, laporan
pembelian, dan HPP — tiga tempat yang akan menghitung barang yang tak pernah
dibeli sebagai pembelian, dan ketiganya baru terbaca salah berbulan-bulan
kemudian.

`pk_purchase_batches.supplier_id` TIDAK dilonggarkan: PK walk-in belum
dikerjakan, dan tembok yang dibuka sebelum ada yang melewatinya adalah tembok
yang dibuka tanpa penjaga.

── `pelanggan_id` PADA TIKET TIMBANG: IDEMPOTEN, DAN INI PERLU DIJELASKAN ──

Dua belas tabel `timbangan_*` dibuat oleh rantai migrasi repo INI (0022), tetapi
`timbangan_transaksi.pelanggan_id` lahir dari rantai repo `timbangan`
(`0027_pelanggan_transaksi`, tabel versi `alembic_version_timbangan`). Di
produksi kolomnya ADA — kedua rantai berjalan di atas basis data yang sama.

Di basis data UJI repo ini ia tidak ada: `tests/pg/` membangun skema dengan
`alembic upgrade head` rantai produksi saja. Begitu pembaca tiket di sini
mengambil `t.pelanggan_id`, seluruh uji yang menyentuh tiket akan gagal dengan
"column does not exist" — kegagalan yang terbacanya seperti kode yang salah,
padahal skemanya yang separuh.

Karena itu ditambahkan dengan penjaga `inspector`: ada → dilewati, tak ada →
dibuat. Pola yang sama sudah dipakai `0022_timbangan.py` untuk
`suppliers.kledo_contact_id`, dengan sebab yang sama.

Revision ID: 0064_jasa
Revises: 0063_sebab_selisih_timbang
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0064_jasa"
down_revision: Union[str, None] = "0063_sebab_selisih_timbang"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Tabel yang mendapat `jasa_id` di irisan ini. Enam, dan urutannya mengikuti
#: aliran barangnya: gabah masuk → dikeringkan → di silo → digiling → dipindah
#: ke Gudang 2 → diterima di Gudang 2.
#:
#: Enam tabel sisanya (`pk_purchase_batches`, `pk_tumpukan_to_silo`,
#: `polishing_process`, `finished_goods_stock`, `byproduct_stock`,
#: `outgoing_records`) menyusul di irisan Gudang 2. Sampai itu, penjaga di
#: `mulai_penyosohan` yang menahan barang jasa supaya tak masuk jalur yang
#: belum bisa membawa pemiliknya.
TABEL_BERJASA = (
    "purchase_batches",
    "drying_lots",
    "silo_storage",
    "milling_process",
    "internal_transfers",
    "pk_gudang2_intakes",
)

#: Nama CHECK "tepat satu dari dua" pada `purchase_batches`. Disebut di dua
#: tempat (upgrade & downgrade), jadi satu konstanta — nama constraint yang
#: diketik dua kali adalah nama yang suatu hari berbeda, dan `DROP CONSTRAINT`
#: yang salah nama gagal tanpa menyebut kenapa.
CK_BELI_ATAU_JASA = "ck_purchase_batches_beli_atau_jasa"


def upgrade() -> None:
    sambung = op.get_bind()
    inspector = sa.inspect(sambung)

    # ── 1 · Pesanan jasa ────────────────────────────────────────────────────
    op.create_table(
        "jasa",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kode", sa.String(20), nullable=False, unique=True),
        sa.Column("pelanggan_id", sa.Integer(), sa.ForeignKey("pelanggan.id"),
                  nullable=False),
        sa.Column("hasil_ditahan", sa.Text(), nullable=False,
                  server_default="sekam,bekatul"),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="berjalan"),
        sa.Column("catatan", sa.Text()),
        sa.Column("dibuat_oleh_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")),
        sa.Column("dibatalkan_pada", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # PARSIAL, dan syaratnya yang menentukan gunanya: satu-satunya pertanyaan
    # yang ditanyakan borang Pos Timbang adalah "pelanggan ini punya pesanan
    # yang masih BERJALAN?" — bukan "pesanan apa saja yang pernah ia punya".
    # Pesanan yang sudah selesai menumpuk bertahun-tahun; yang berjalan
    # segelintir.
    op.create_index("ix_jasa_pelanggan_berjalan", "jasa", ["pelanggan_id"],
                    postgresql_where=sa.text("status = 'berjalan'"),
                    sqlite_where=sa.text("status = 'berjalan'"))

    # ── 2 · Satu kolom, enam tabel ──────────────────────────────────────────
    for tabel in TABEL_BERJASA:
        op.add_column(tabel, sa.Column(
            "jasa_id", sa.Integer(), sa.ForeignKey("jasa.id"), nullable=True))
        # PARSIAL juga, dan sebabnya sama: baris berpemilik adalah segelintir
        # di antara riwayat bertahun-tahun baris pabrik. Indeks penuh atas
        # kolom yang 99% NULL membayar biaya tulisnya tanpa mempercepat
        # satu pun kueri yang dipakai. Pola yang sudah dipakai
        # `ix_silo_storage_giling`.
        op.create_index(
            f"ix_{tabel}_jasa", tabel, ["jasa_id"],
            postgresql_where=sa.text("jasa_id IS NOT NULL"),
            sqlite_where=sa.text("jasa_id IS NOT NULL"))

    # ── 3 · Tembok "semua gabah dibeli" dibuka, penjaganya diganti ──────────
    op.alter_column("purchase_batches", "supplier_id", nullable=True,
                    existing_type=sa.Integer())
    if sambung.dialect.name != "sqlite":
        # SQLite tak bisa menambah CHECK pada tabel yang sudah ada sama sekali.
        # Postgres tetap mendapatnya: aturan "dibeli ATAU dititipkan" terlalu
        # berharga untuk dilepas demi menyenangkan dialek uji. Kalimat yang
        # sama sudah tertulis di `0027_pelanggan_transaksi` repo timbangan.
        op.execute(
            f"ALTER TABLE purchase_batches ADD CONSTRAINT {CK_BELI_ATAU_JASA} "
            "CHECK ((supplier_id IS NOT NULL) <> (jasa_id IS NOT NULL))"
        )

    # ── 4 · Tiket timbang: pemilik & penunjuk pesanan ───────────────────────
    kolom_tiket = {c["name"] for c in inspector.get_columns("timbangan_transaksi")}
    if "pelanggan_id" not in kolom_tiket:
        # Lihat catatan panjang di kepala berkas: kolomnya milik rantai repo
        # `timbangan`, dan di basis data uji repo ini rantai itu tak pernah
        # berjalan.
        op.add_column("timbangan_transaksi",
                      sa.Column("pelanggan_id", sa.Integer()))
        if sambung.dialect.name != "sqlite":
            op.create_foreign_key(
                "fk_timbangan_transaksi_pelanggan", "timbangan_transaksi",
                "pelanggan", ["pelanggan_id"], ["id"])
    # Penunjuk ke pesanan yang SUDAH berjalan. Tanpa ini, Pak Budi yang
    # menjasakan 24 ton dengan truk 12 ton melahirkan DUA pesanan — dua nota,
    # dua rendemen, dan `pastikan_satu_jasa()` yang menolak menggiling keduanya
    # bersama: benar menurut aturannya, salah menurut kenyataannya.
    #
    # Baris `jasa` TIDAK dibuat Pos Timbang. Tiket bisa dibatalkan atau
    # direvisi (`status_transaksi='VOID'`, `jumlah_revisi`), dan tiket batal
    # yang sudah melahirkan pesanan akan meninggalkan pesanan yatim. Pesanannya
    # lahir saat operator produksi MENERIMA tiketnya — arah yang sudah dipakai
    # `purchase_batches.timbangan_transaksi_id` hari ini.
    op.add_column("timbangan_transaksi", sa.Column(
        "jasa_id", sa.Integer(), sa.ForeignKey("jasa.id"), nullable=True))
    op.create_index(
        "ix_timbangan_transaksi_jasa", "timbangan_transaksi", ["jasa_id"],
        postgresql_where=sa.text("jasa_id IS NOT NULL"),
        sqlite_where=sa.text("jasa_id IS NOT NULL"))


def downgrade() -> None:
    sambung = op.get_bind()

    op.drop_index("ix_timbangan_transaksi_jasa", table_name="timbangan_transaksi")
    op.drop_column("timbangan_transaksi", "jasa_id")
    # `pelanggan_id` TIDAK dijatuhkan: ia milik rantai repo `timbangan`, dan
    # menjatuhkannya dari sini akan merobohkan Pos Timbang di produksi —
    # layanan yang tak pernah meminta migrasi ini turun.

    if sambung.dialect.name != "sqlite":
        op.execute(
            f"ALTER TABLE purchase_batches DROP CONSTRAINT IF EXISTS {CK_BELI_ATAU_JASA}")
    # Dikembalikan NOT NULL. Gagal bila ada baris jasa yang tertinggal — dan
    # itu BENAR: menjatuhkannya diam-diam berarti membuang catatan barang milik
    # orang lain. Yang ingin turun harus membereskan barisnya lebih dulu.
    op.alter_column("purchase_batches", "supplier_id", nullable=False,
                    existing_type=sa.Integer())

    for tabel in TABEL_BERJASA:
        op.drop_index(f"ix_{tabel}_jasa", table_name=tabel)
        op.drop_column(tabel, "jasa_id")

    op.drop_index("ix_jasa_pelanggan_berjalan", table_name="jasa")
    op.drop_table("jasa")
