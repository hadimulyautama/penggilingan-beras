"""Modul Timbangan: 12 tabel `timbangan_*` + kolom jembatan Kledo pada `suppliers`.

Murni timbangan — TIDAK ADA kolom harga atau nilai uang di mana pun. Operator
pos timbang tidak boleh mengetahui harga; larangan itu ditegakkan oleh
ketiadaan kolom.

Revision ID: 0022_timbangan
Revises: 0021_kantor_rbac
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_timbangan"
down_revision: Union[str, None] = "0021_kantor_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KG = sa.Numeric(14, 3)
KG_KECIL = sa.Numeric(9, 4)
PCT = sa.Numeric(9, 4)


def _stamp() -> list:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Jembatan sinkronisasi Kledo (idempoten: kolom mungkin sudah ada) ──
    kolom_suppliers = {c["name"] for c in inspector.get_columns("suppliers")}
    if "kledo_contact_id" not in kolom_suppliers:
        op.add_column("suppliers", sa.Column("kledo_contact_id", sa.BigInteger()))
        op.create_index(
            "ix_suppliers_kledo_contact_id", "suppliers", ["kledo_contact_id"]
        )

    # ── Master aturan per komoditas ──────────────────────────────────────
    op.create_table(
        "timbangan_jenis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kode", sa.String(30), nullable=False, unique=True),
        sa.Column("nama", sa.String(80), nullable=False),
        sa.Column("urutan", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("arah", sa.String(10), nullable=False),
        sa.Column("acuan", sa.String(24), nullable=False),
        sa.Column("sumber_tara", sa.String(20), nullable=False),
        sa.Column("tara_tetap_kg", KG_KECIL, nullable=False, server_default="0"),
        sa.Column("tara_bawaan_kg", KG_KECIL, nullable=False, server_default="0"),
        sa.Column("ambang_jenis", sa.String(24), nullable=False),
        sa.Column("ambang_nilai", KG_KECIL, nullable=False, server_default="0"),
        sa.Column("ambang_arah", sa.String(28), nullable=False),
        sa.Column("ambang_investigasi_nilai", KG_KECIL),
        sa.Column("rahasia", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cetak_bukti", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "masa_berlaku_tara_hari", sa.Integer(), nullable=False, server_default="90"
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="aktif"),
        sa.Column("catatan", sa.Text()),
        *_stamp(),
    )

    # ── Akun login ───────────────────────────────────────────────────────
    op.create_table(
        "timbangan_akun",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("nama", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="PETUGAS"),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="aktif"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("perangkat_kode", sa.String(8)),
        sa.Column("terakhir_login", sa.DateTime(timezone=True)),
        *_stamp(),
    )

    op.create_table(
        "timbangan_kendaraan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nomor_polisi", sa.String(20), nullable=False, unique=True),
        sa.Column("catatan", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="aktif"),
        *_stamp(),
    )
    op.create_index(
        "ix_timbangan_kendaraan_nomor_polisi", "timbangan_kendaraan", ["nomor_polisi"]
    )

    op.create_table(
        "timbangan_supplier_profil",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"),
            nullable=False, unique=True,
        ),
        sa.Column("wilayah", sa.String(100)),
        sa.Column(
            "status_monitoring", sa.String(20), nullable=False, server_default="AKTIF"
        ),
        sa.Column("catatan", sa.Text()),
        *_stamp(),
    )

    # ── Tara standar (append-only) ───────────────────────────────────────
    op.create_table(
        "timbangan_tara_standar",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id")),
        sa.Column("jenis_kode", sa.String(30), nullable=False),
        sa.Column("jumlah_sampel", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_berat_kg", KG_KECIL, nullable=False, server_default="0"),
        sa.Column("tara_per_karung_kg", KG_KECIL, nullable=False),
        sa.Column("jenis_karung", sa.String(60)),
        sa.Column("berlaku_mulai", sa.Date(), nullable=False),
        sa.Column("berlaku_sampai", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False, server_default="BERLAKU"),
        sa.Column("alasan", sa.Text()),
        sa.Column("dibuat_oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),
        sa.Column("disetujui_oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),
        sa.Column("disetujui_pada", sa.DateTime(timezone=True)),
        *_stamp(),
    )
    op.create_index(
        "ix_timbangan_tara_standar_berlaku", "timbangan_tara_standar",
        ["supplier_id", "jenis_kode", "status"],
    )

    # ── Transaksi ────────────────────────────────────────────────────────
    op.create_table(
        "timbangan_transaksi",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kode", sa.String(32), nullable=False, unique=True),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("arah", sa.String(10), nullable=False),
        sa.Column("jenis_kode", sa.String(30), nullable=False),
        sa.Column(
            "cara_timbang", sa.String(12), nullable=False, server_default="DUA_KALI"
        ),
        sa.Column("aturan_snapshot", sa.Text()),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id")),
        sa.Column("pihak_nama", sa.String(120)),
        sa.Column(
            "kendaraan_id", sa.Integer(), sa.ForeignKey("timbangan_kendaraan.id")
        ),
        sa.Column("nomor_polisi", sa.String(20)),
        sa.Column("nama_sopir", sa.String(100)),

        sa.Column("timbang1_kg", KG, nullable=False),
        sa.Column("timbang1_waktu", sa.DateTime(timezone=True)),
        sa.Column("timbang1_waktu_sistem", sa.DateTime(timezone=True)),
        sa.Column(
            "timbang1_petugas_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")
        ),
        sa.Column("timbang2_kg", KG),
        sa.Column("timbang2_waktu", sa.DateTime(timezone=True)),
        sa.Column("timbang2_waktu_sistem", sa.DateTime(timezone=True)),
        sa.Column(
            "timbang2_petugas_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")
        ),

        sa.Column("berat_bermuatan_kg", KG),
        sa.Column("berat_kosong_kg", KG),
        sa.Column("tara_lain_kg", KG, nullable=False, server_default="0"),

        sa.Column("netto_timbangan_kg", KG),
        sa.Column("jumlah_karung", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tara_kg", KG, nullable=False, server_default="0"),
        sa.Column("berat_barang_kg", KG),
        sa.Column("berat_acuan_kg", KG, nullable=False, server_default="0"),
        sa.Column("selisih_kg", KG, nullable=False, server_default="0"),
        sa.Column("selisih_persen", PCT, nullable=False, server_default="0"),
        sa.Column("batas_bawah_kg", KG),
        sa.Column("batas_atas_kg", KG),
        sa.Column("status_kontrol", sa.String(24)),
        sa.Column("keterangan", sa.Text()),

        sa.Column(
            "status_tiket", sa.String(16), nullable=False, server_default="TERBUKA"
        ),
        sa.Column(
            "status_transaksi", sa.String(10), nullable=False, server_default="AKTIF"
        ),
        sa.Column("tutup_paksa_alasan", sa.Text()),
        sa.Column("terkunci", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dikunci_pada", sa.DateTime(timezone=True)),
        sa.Column("jumlah_revisi", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("void_alasan", sa.Text()),
        sa.Column("void_oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),
        sa.Column("void_pada", sa.DateTime(timezone=True)),
        sa.Column("catatan", sa.Text()),

        sa.Column("perangkat_kode", sa.String(8)),
        sa.Column(
            "dibuat_offline", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("dikirim_pada", sa.DateTime(timezone=True)),
        sa.Column("dibuat_oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),
        sa.Column("diubah_oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),

        sa.Column(
            "purchase_batch_id", sa.Integer(), sa.ForeignKey("purchase_batches.id")
        ),
        sa.Column(
            "pk_purchase_batch_id", sa.Integer(),
            sa.ForeignKey("pk_purchase_batches.id"),
        ),
        *_stamp(),
    )
    for nama, kolom in (
        ("ix_timbangan_transaksi_kode", ["kode"]),
        ("ix_timbangan_transaksi_tanggal", ["tanggal"]),
        ("ix_timbangan_transaksi_arah", ["arah"]),
        ("ix_timbangan_transaksi_jenis_kode", ["jenis_kode"]),
        ("ix_timbangan_transaksi_nomor_polisi", ["nomor_polisi"]),
        ("ix_timbangan_transaksi_status_kontrol", ["status_kontrol"]),
        ("ix_timbangan_transaksi_status_tiket", ["status_tiket"]),
        ("ix_timbangan_transaksi_status_transaksi", ["status_transaksi"]),
        ("ix_timbangan_transaksi_tanggal_supplier", ["tanggal", "supplier_id"]),
        ("ix_timbangan_transaksi_tiket", ["status_tiket", "tanggal"]),
    ):
        op.create_index(nama, "timbangan_transaksi", kolom)

    # ── Baris muatan ─────────────────────────────────────────────────────
    op.create_table(
        "timbangan_muatan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "transaksi_id", sa.Integer(),
            sa.ForeignKey("timbangan_transaksi.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("urutan", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("jenis_kode", sa.String(30), nullable=False),
        sa.Column("nomor_acuan", sa.String(50)),
        sa.Column("jumlah_karung", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tara_per_karung_kg", KG_KECIL, nullable=False, server_default="0"),
        sa.Column("berat_acuan_kg", KG, nullable=False, server_default="0"),
        sa.Column(
            "tara_standar_id", sa.Integer(),
            sa.ForeignKey("timbangan_tara_standar.id"),
        ),
        sa.Column("catatan", sa.Text()),
    )
    op.create_index("ix_timbangan_muatan_nomor_acuan", "timbangan_muatan", ["nomor_acuan"])

    # ── Pemeriksaan (SOP butir 6) ────────────────────────────────────────
    op.create_table(
        "timbangan_pemeriksaan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "transaksi_id", sa.Integer(), sa.ForeignKey("timbangan_transaksi.id"),
            nullable=False,
        ),
        sa.Column("langkah_ulang_timbang", sa.Text()),
        sa.Column("langkah_hitung_karung", sa.Text()),
        sa.Column("langkah_periksa_tara", sa.Text()),
        sa.Column("langkah_periksa_dokumen", sa.Text()),
        sa.Column("langkah_periksa_muatan", sa.Text()),
        sa.Column("langkah_lapor", sa.Text()),
        sa.Column("dilaporkan_ke", sa.String(120)),
        sa.Column("dilaporkan_pada", sa.DateTime(timezone=True)),
        sa.Column("kategori_hasil", sa.String(30)),
        sa.Column("catatan_resolusi", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False, server_default="DIBUKA"),
        sa.Column("dibuka_oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),
        sa.Column("ditutup_oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),
        sa.Column("ditutup_pada", sa.DateTime(timezone=True)),
        *_stamp(),
    )
    op.create_index(
        "ix_timbangan_pemeriksaan_transaksi", "timbangan_pemeriksaan", ["transaksi_id"]
    )
    op.create_index(
        "ix_timbangan_pemeriksaan_status", "timbangan_pemeriksaan", ["status"]
    )
    op.create_index(
        "ix_timbangan_pemeriksaan_kategori_hasil",
        "timbangan_pemeriksaan", ["kategori_hasil"],
    )

    # ── Riwayat cetak ────────────────────────────────────────────────────
    op.create_table(
        "timbangan_cetak",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "transaksi_id", sa.Integer(), sa.ForeignKey("timbangan_transaksi.id"),
            nullable=False,
        ),
        sa.Column("urutan", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ulang", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("alasan", sa.Text()),
        sa.Column("oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),
        sa.Column(
            "waktu", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("transaksi_id", "urutan", name="uq_timbangan_cetak_urutan"),
    )
    op.create_index("ix_timbangan_cetak_transaksi", "timbangan_cetak", ["transaksi_id"])

    # ── Foto bukti ───────────────────────────────────────────────────────
    op.create_table(
        "timbangan_foto",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "transaksi_id", sa.Integer(),
            sa.ForeignKey("timbangan_transaksi.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("jenis", sa.String(20), nullable=False, server_default="LAIN"),
        sa.Column("nama_file", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False, server_default="image/jpeg"),
        sa.Column("ukuran_byte", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("konten", sa.LargeBinary(), nullable=False),
        sa.Column("diunggah_oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )

    # ── Skor & audit ─────────────────────────────────────────────────────
    op.create_table(
        "timbangan_skor_supplier",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False
        ),
        sa.Column("periode", sa.String(10), nullable=False, server_default="TERKINI"),
        sa.Column("skor_total", PCT, nullable=False, server_default="0"),
        sa.Column("kategori", sa.String(2), nullable=False, server_default="C"),
        sa.Column("jumlah_transaksi", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("komponen_json", sa.Text()),
        sa.Column("pola_json", sa.Text()),
        sa.Column(
            "dihitung_pada", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "supplier_id", "periode", name="uq_timbangan_skor_supplier_periode"
        ),
    )
    op.create_index(
        "ix_timbangan_skor_supplier_supplier", "timbangan_skor_supplier", ["supplier_id"]
    )

    op.create_table(
        "timbangan_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "waktu", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("akun_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")),
        sa.Column("akun_nama", sa.String(100)),
        sa.Column("aksi", sa.String(40), nullable=False),
        sa.Column("entitas", sa.String(40)),
        sa.Column("entitas_id", sa.String(40)),
        sa.Column("ringkasan", sa.Text()),
        sa.Column("nilai_sebelum", sa.Text()),
        sa.Column("nilai_sesudah", sa.Text()),
        sa.Column("perangkat_kode", sa.String(8)),
        sa.Column("ip", sa.String(45)),
    )
    op.create_index("ix_timbangan_audit_waktu", "timbangan_audit", ["waktu"])
    op.create_index("ix_timbangan_audit_aksi", "timbangan_audit", ["aksi"])


def downgrade() -> None:
    for tabel in (
        "timbangan_audit",
        "timbangan_skor_supplier",
        "timbangan_foto",
        "timbangan_cetak",
        "timbangan_pemeriksaan",
        "timbangan_muatan",
        "timbangan_transaksi",
        "timbangan_tara_standar",
        "timbangan_supplier_profil",
        "timbangan_kendaraan",
        "timbangan_akun",
        "timbangan_jenis",
    ):
        op.drop_table(tabel)

    bind = op.get_bind()
    kolom = {c["name"] for c in sa.inspect(bind).get_columns("suppliers")}
    if "kledo_contact_id" in kolom:
        op.drop_index("ix_suppliers_kledo_contact_id", table_name="suppliers")
        op.drop_column("suppliers", "kledo_contact_id")
