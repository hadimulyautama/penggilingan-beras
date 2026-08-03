"""MCP server: ekspos data & simulasi penggilingan beras ke agent (Hermes/Claude).

Membungkus service aplikasi yang sudah ada sebagai MCP tools — SATU sumber
kebenaran, rumus & angka selalu sinkron dengan aplikasi. READ-ONLY (belum ada
tool yang menulis/mengubah data).

Transport (via env MCP_TRANSPORT):
  - "stdio" (default)  : untuk Cowork/Claude Desktop di mesin yang sama.
  - "http"             : streamable-HTTP untuk agent remote (mis. Hermes di
                         VPS Hostinger). WAJIB set MCP_AUTH_TOKEN — tiap request
                         harus membawa header  Authorization: Bearer <token>.

Env lain:
  - MCP_AUTH_TOKEN : token bearer wajib saat transport http.
  - PORT           : port HTTP (default 8080).
  - DATABASE_URL   : dipakai tool read (default menunjuk Postgres lokal).

Jalankan:
  stdio :  python mcp_server.py
  http  :  MCP_TRANSPORT=http MCP_AUTH_TOKEN=xxxx PORT=8080 python mcp_server.py
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.config import settings
from app.database import SessionLocal
from app.services.analytics import (
    hpp_trend as _hpp_trend,
    rekap_produksi_bulanan as _rekap_produksi,
    simulasi_hpp as _simulasi_hpp,
)

# Matikan proteksi DNS-rebinding FastMCP (default hanya izinkan host localhost →
# menolak domain Railway dengan 421 "Invalid Host header"). Aman di sini karena
# akses server-to-server sudah dijaga token bearer, bukan konteks browser.
mcp = FastMCP(
    "penggilingan-beras",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    ),
)


# ─────────────────────────── Simulasi (murni) ───────────────────────────
@mcp.tool()
def simulasi_hpp(
    harga_gabah: float,
    berat_bahan_kg: float,
    rendemen_persen: float | None = None,
    berat_hasil_kg: float | None = None,
    kondisi: str = "basah",
    langsung_silo: bool = False,
) -> str:
    """Simulasi (what-if) HPP beras pecah kulit (PK) dari harga gabah & rendemen.

    Menghitung HPP per kg PK memakai tarif biaya terkini pabrik (bongkar,
    pengeringan, operator FLAT per proses, rubber roll, listrik, tenaga giling).
    Murni skenario angka — TIDAK memakai data batch/stok nyata.

    Args:
        harga_gabah: Harga beli gabah, Rp per kg (mis. 7800).
        berat_bahan_kg: Tonase gabah masuk dalam KG (mis. 10000 = 10 ton). WAJIB —
            biaya operator flat per proses dibagi tonase ini.
        rendemen_persen: Rendemen (%) mis. 64. Boleh kosong bila berat_hasil_kg
            diisi (rendemen dihitung otomatis = hasil/bahan).
        berat_hasil_kg: Tonase hasil PK dalam KG (mis. 6400). Menghitung rendemen
            bila rendemen_persen kosong.
        kondisi: 'basah' (default, dikeringkan) atau 'kering'.
        langsung_silo: True bila gabah kering langsung ke silo tanpa pengeringan.
    """
    if kondisi not in ("basah", "kering"):
        return "kondisi harus 'basah' atau 'kering'."
    return _simulasi_hpp(
        harga_gabah, rendemen_persen, kondisi=kondisi,
        langsung_silo=langsung_silo, berat_bahan=berat_bahan_kg,
        berat_hasil=berat_hasil_kg,
    )


@mcp.tool()
def tarif_biaya_terkini() -> dict:
    """Tarif biaya produksi (Rp) yang menjadi asumsi simulasi HPP."""
    s = settings
    return {
        "biaya_bongkar_per_kg_gabah": s.biaya_bongkar_per_kg_gabah,
        "biaya_operator_per_proses_milling": s.biaya_operator_per_proses,
        "biaya_tenaga_milling_per_kg_pk": s.biaya_tenaga_milling_per_kg_pk,
        "biaya_pengeringan_basah_per_kg": s.biaya_pengeringan_basah_per_kg,
        "biaya_pengeringan_kering_per_kg": s.biaya_pengeringan_kering_per_kg,
        "biaya_listrik_milling_per_kg_gabah": s.biaya_listrik_milling_per_kg_gabah,
        "rubber_roll_harga_per_set": s.rubber_roll_harga_per_set,
        "rubber_roll_umur_ton": s.rubber_roll_umur_ton,
        "rendemen_asumsi_persen": s.rendemen_asumsi_persen,
    }


# ─────────────────────────── Data nyata (read-only) ───────────────────────────
@mcp.tool()
async def stok_gudang1() -> str:
    """Status Gudang 1 (Selepan): gabah, pengeringan, silo, giling, PK siap kirim."""
    from app.services.report import status_gudang1
    from app.services.transfer import laporan_pk_siap_transfer
    async with SessionLocal() as db:
        return (await status_gudang1(db)) + "\n\n" + (await laporan_pk_siap_transfer(db))


@mcp.tool()
async def stok_gudang2() -> str:
    """Stok PK Gudang 2 (Penyosohan): silo A/B (+ HPP rata-rata) + tumpukan."""
    from app.gudang2.service import laporan_stok_gudang2
    async with SessionLocal() as db:
        return await laporan_stok_gudang2(db, financial=True)


@mcp.tool()
async def stok_barang_jadi() -> str:
    """Stok barang jadi (beras per jenis) + bekatul curah."""
    from app.inventory.finished_goods import hitung_stok_bekatul, laporan_stok_barang_jadi
    async with SessionLocal() as db:
        bekatul = float(await hitung_stok_bekatul(db))
        return (await laporan_stok_barang_jadi(db)) + f"\n\n🌾 Bekatul curah: {bekatul:,.0f} kg"


@mcp.tool()
async def stok_kemasan() -> str:
    """Stok kemasan (karung) per merk/jenis/ukuran."""
    from app.inventory.packaging import laporan_stok_kemasan
    async with SessionLocal() as db:
        return await laporan_stok_kemasan(db)


@mcp.tool()
async def hpp_beras_tren() -> str:
    """Tren HPP beras dari proses penyosohan terakhir (per periode)."""
    async with SessionLocal() as db:
        return await _hpp_trend(db)


@mcp.tool()
async def rekap_produksi_bulanan() -> str:
    """Rekap produksi PK per bulan + utilisasi vs kapasitas dryer."""
    async with SessionLocal() as db:
        return await _rekap_produksi(db)


@mcp.tool()
async def item_nyangkut() -> str:
    """Item 'nyangkut' lintas siklus yang perlu tindakan (gabah/dryer/silo/giling/
    penyosohan/verifikasi). Berguna sebagai peringatan proaktif untuk manajemen."""
    from app.services.pemantau import pemantau_nyangkut
    async with SessionLocal() as db:
        return await pemantau_nyangkut(db, financial=True, scope="all")


# ═══════════════════════ Kantor AI (arsip/dokumen) ═══════════════════════
# Dipanggil oleh agent (Hermes) untuk memandu arsip & mengelola dokumen.
# Logika + guardrail ada di sini (deterministik) — bukan di kebebasan LLM.
@mcp.tool()
def panduan_arsip(nama_dokumen: str, isi_ringkas: str = "") -> str:
    """Panduan menyimpan sebuah dokumen: folder DIGITAL + ordner FISIK (warna/
    golongan/retensi) sesuai Pedoman Kearsipan PT HMU.

    Args:
        nama_dokumen: nama/judul dokumen (mis. 'Kontrak Kerja PKWT - Budi').
        isi_ringkas: cuplikan isi (opsional) untuk klasifikasi lebih tepat.
    """
    from app.kantor import arsip_fisik as af
    from app.kantor.drive import taksonomi as tx

    tebak = tx.tebak_kategori(nama_dokumen, isi_ringkas)
    if not tebak:
        return ("Belum yakin dari nama saja — perlu lihat isi dokumen. "
                "Kategori digital tersedia 00–11.")
    p = af.panduan(tebak[0][0])
    baris = [f"📄 {nama_dokumen}",
             f"🗂️ Digital: folder {p.digital_kode} - {p.digital_nama}"]
    if p.fisik:
        f = p.fisik
        baris.append(f"📁 Fisik: ordner {f.kode} {f.nama} (stiker {f.warna}) · "
                     f"golongan {f.golongan} · simpan {f.retensi}")
    if p.catatan:
        baris.append(f"ℹ️ {p.catatan}")
    return "\n".join(baris)


@mcp.tool()
def cek_nama_file(nama: str) -> str:
    """Periksa nama file terhadap konvensi kearsipan + usulkan nama baku."""
    from app.kantor.dokumen import konsistensi as kons
    h = kons.validasi_nama_file(nama)
    if h.ok and not h.nama_usulan:
        return f"✅ '{nama}' sudah sesuai konvensi."
    masalah = "; ".join(t.pesan for t in h.temuan) or "—"
    usul = f"\nUsulan: {h.nama_usulan}" if h.nama_usulan else ""
    return f"Nama: {nama}\nTemuan: {masalah}{usul}"


@mcp.tool()
async def terbitkan_nomor_surat(
    kode: str, divisi: str, bulan: int, tahun: int,
    perihal: str = "", pihak: str = "",
) -> str:
    """Terbitkan & catat nomor surat resmi (register anti-bentrok, reset tahunan).

    Format: NNN/KODE/DIVISI/PT-HMU/BULAN(Romawi)/TAHUN.
    Kode mis. CSR/SK/SPK/ST/SP/BA/SPPD/BAST/TTPH/PKL. Divisi mis. HR/KEU/OPS.
    """
    from app.kantor.dokumen import penomoran
    async with SessionLocal() as db:
        try:
            row = await penomoran.terbitkan_nomor_surat(
                db, kode=kode, divisi=divisi, bulan=bulan, tahun=tahun,
                perihal=perihal or None, pihak=pihak or None,
            )
        except (ValueError, RuntimeError) as e:
            return f"Gagal terbitkan nomor: {e}"
    return f"✅ Nomor terbit: {row.nomor_lengkap}"


@mcp.tool()
def buat_surat_tugas(
    nomor: str, nama: str, jabatan: str, tugas: str,
    tempat: str, waktu: str, tanggal: str, no_pegawai: str = "-",
) -> str:
    """Susun naskah Surat Tugas berkop resmi PT HMU. `tanggal` = YYYY-MM-DD."""
    from datetime import date
    from app.kantor.dokumen import surat
    try:
        d = date.fromisoformat(tanggal)
    except ValueError:
        return "tanggal harus format YYYY-MM-DD."
    return surat.surat_tugas(nomor=nomor, nama=nama, jabatan=jabatan, tugas=tugas,
                             tempat=tempat, waktu=waktu, tanggal=d, no_pegawai=no_pegawai)


# ═══════════════════════ Google Drive (baca-saja) ═══════════════════════
# Tool arsip untuk agent: melihat isi folder & mencari file. TIDAK mengubah apa
# pun (pindah/rename/hapus di-hold — perlu mekanisme persetujuan tersendiri).
def _drive_client():
    from app.kantor.drive import client as drv
    if not drv.terkonfigurasi():
        return None
    return drv.DriveClient()


def _fmt_isi(items) -> str:
    if not items:
        return "(kosong)"
    baris = []
    for f in sorted(items, key=lambda x: (not x.is_folder, x.nama.lower())):
        if f.is_folder:
            baris.append(f"📁 {f.nama}/")
        else:
            sz = f" · {f.size / 1024:.0f} KB" if f.size else ""
            baris.append(f"📄 {f.nama}{sz}")
    return "\n".join(baris)


_DRIVE_OFF = "Google Drive belum terkonfigurasi di server MCP (env GDRIVE_OAUTH_* belum ada)."


@mcp.tool()
def daftar_transit() -> str:
    """Daftar isi folder _TRANSIT (INBOX file baru) di Google Drive PT HMU.

    Read-only. _TRANSIT adalah tempat file baru masuk sebelum diarsipkan ke
    kategori yang benar. Pakai untuk 'apa saja file di inbox/transit'.
    """
    from app.kantor.drive import mapper, taksonomi as tx
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    for f in c.anak():
        if f.is_folder and mapper.kode_kategori(f.nama) == tx.TRANSIT:
            isi = c.anak(f.id)
            return f"📥 {f.nama} — {len(isi)} item:\n{_fmt_isi(isi)}"
    return "Folder _TRANSIT tidak ditemukan di root Shared Drive."


@mcp.tool()
def daftar_folder(kategori: str) -> str:
    """Daftar isi sebuah folder kategori di Google Drive PT HMU (read-only).

    Args:
        kategori: kode kategori ('00'–'11' / '99') ATAU sebagian nama folder
            (mis. 'SDM', 'Keuangan'). Kategori 00=Legalitas, 03=SDM, dst.
    """
    from app.kantor.drive import mapper
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    q = kategori.strip().lower()
    for f in c.anak():
        if not f.is_folder:
            continue
        if mapper.kode_kategori(f.nama) == kategori.strip() or q in f.nama.lower():
            isi = c.anak(f.id)
            return f"🗂️ {f.nama} — {len(isi)} item:\n{_fmt_isi(isi)}"
    return f"Folder kategori '{kategori}' tidak ditemukan di root Shared Drive."


@mcp.tool()
def cari_file(kata: str) -> str:
    """Cari file/folder di Google Drive PT HMU yang namanya mengandung `kata`.

    Read-only. Kembalikan sampai 50 hasil teratas (nama + ukuran).
    """
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    hasil = c.cari(kata, maks=50)
    if not hasil:
        return f"Tidak ada file yang namanya mengandung '{kata}'."
    return f"🔎 {len(hasil)} hasil untuk '{kata}':\n{_fmt_isi(hasil)}"


# ═══════════════════ Google Drive — TULIS (usul → konfirmasi) ═══════════════════
# Aksi konsekuensial (memindahkan file asli). Pola: usul_pindah_file (pratinjau +
# token, TIDAK eksekusi) → jalankan_pindah (eksekusi hanya bila token cocok).
# Selalu REVERSIBLE (pindah, bukan hapus) & dicatat di kantor_audit_log.
def _token_pindah(file_id: str, dest_id: str) -> str:
    import hashlib
    import hmac as _hmac
    secret = os.environ.get("MCP_AUTH_TOKEN", "kantor").encode()
    return _hmac.new(secret, f"{file_id}|{dest_id}".encode(), hashlib.sha256).hexdigest()[:10]


async def _audit_kantor(aksi: str, target: str, detail: dict, status: str) -> None:
    import json
    try:
        from app.kantor.models import KantorAuditLog
        async with SessionLocal() as db:
            db.add(KantorAuditLog(
                peran="kantor", aksi=aksi, target=target,
                detail=json.dumps(detail, ensure_ascii=False), status=status,
            ))
            await db.commit()
    except Exception:
        pass  # audit gagal tak boleh menggagalkan aksi utama


@mcp.tool()
def usul_pindah_file(nama: str, tujuan: str) -> str:
    """USUL memindahkan file ke folder kategori lain — TIDAK langsung dieksekusi.

    Aksi ini MENGUBAH Google Drive → WAJIB persetujuan pengguna. Alur: panggil
    ini dulu untuk pratinjau + token, TUNJUKKAN ke pengguna, dan HANYA setelah
    pengguna menyetujui secara eksplisit ('ya'), panggil `jalankan_pindah`.
    JANGAN memanggil jalankan_pindah tanpa persetujuan pengguna.

    Args:
        nama: nama file (atau sebagian) yang mau dipindah — harus cocok 1 file.
        tujuan: kode kategori tujuan ('00'–'11'/'99') atau sebagian nama folder.
    """
    from app.kantor.drive import mapper
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    kandidat = [f for f in c.cari(nama, maks=20) if not f.is_folder]
    if not kandidat:
        return f"Tidak ada file yang namanya mengandung '{nama}'."
    if len(kandidat) > 1:
        daftar = "\n".join(f"• {f.nama}" for f in kandidat[:10])
        return f"Ada {len(kandidat)} file cocok '{nama}' — sebutkan lebih spesifik:\n{daftar}"
    f = kandidat[0]
    q = tujuan.strip().lower()
    dest = next(
        (r for r in c.anak() if r.is_folder and (
            mapper.kode_kategori(r.nama) == tujuan.strip() or q in r.nama.lower())),
        None,
    )
    if dest is None:
        return f"Folder tujuan '{tujuan}' tidak ditemukan di root Shared Drive."
    tok = _token_pindah(f.id, dest.id)
    return (
        "📋 USUL PINDAH (BELUM dijalankan):\n"
        f"• File   : {f.nama}\n"
        f"• Ke     : {dest.nama}\n"
        "⚠️ Ini mengubah Drive — minta persetujuan pengguna dulu. Setelah pengguna "
        "setuju ('ya'), panggil:\n"
        f"jalankan_pindah(file_id='{f.id}', tujuan_id='{dest.id}', token='{tok}')"
    )


@mcp.tool()
async def jalankan_pindah(file_id: str, tujuan_id: str, token: str) -> str:
    """Eksekusi pemindahan file yang SUDAH disetujui pengguna.

    Butuh `token` dari usul_pindah_file (mengikat aksi ke file+tujuan tertentu).
    Reversible (pindah, bukan hapus) & dicatat di audit. HANYA panggil setelah
    pengguna menyetujui usulan secara eksplisit.
    """
    if token != _token_pindah(file_id, tujuan_id):
        return ("❌ Token tidak cocok. Panggil usul_pindah_file dulu, tunjukkan "
                "usulannya ke pengguna, baru jalankan setelah disetujui.")
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    try:
        c.pindah(file_id, tujuan_id)
    except Exception as e:
        await _audit_kantor("pindah_drive", file_id, {"tujuan": tujuan_id, "error": str(e)[:200]}, "gagal")
        return f"Gagal memindah file: {e}"
    await _audit_kantor("pindah_drive", file_id, {"tujuan": tujuan_id}, "sukses")
    return "✅ File dipindah ke folder tujuan. (Reversible & tercatat di audit.)"


# ═══════════════ Google Drive — BACA ISI + RENAME (usul → konfirmasi) ═══════════════
# Rename berbasis ISI: agent baca dokumen, usulkan nama sesuai isi + konvensi
# (Title Case, tanpa copy/final/fix/(n)/versi, pertahankan akronim & tanggal),
# lalu setelah disetujui → jalankan. Reversible (nama lama dicatat di audit).
def _token_rename(file_id: str, nama_baru: str) -> str:
    import hashlib
    import hmac as _hmac
    secret = os.environ.get("MCP_AUTH_TOKEN", "kantor").encode()
    return _hmac.new(secret, f"rename|{file_id}|{nama_baru}".encode(), hashlib.sha256).hexdigest()[:10]


@mcp.tool()
def baca_dokumen(nama: str) -> str:
    """Baca & kembalikan ISI teks sebuah dokumen di Drive PT HMU (read-only).

    Untuk MEMAHAMI isi file — mis. sebelum mengusulkan nama baru yang sesuai isi.
    Mendukung Google Docs/Sheets/Slides, docx, dan PDF. File gambar/scan → tak
    terekstrak (namai dari konteks lain).

    Args:
        nama: nama file (persis lebih baik) yang mau dibaca.
    """
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    kand = [x for x in c.cari(nama, maks=25) if not x.is_folder and x.nama == nama]
    if not kand:
        kand = [x for x in c.cari(nama, maks=25) if not x.is_folder]
    if not kand:
        return f"File '{nama}' tidak ditemukan."
    if len(kand) > 1:
        return "Beberapa file cocok — sebut nama persis:\n" + "\n".join(f"• {f.nama}" for f in kand[:10])
    f = kand[0]
    try:
        mime = c._service().files().get(
            fileId=f.id, fields="mimeType", supportsAllDrives=True).execute()["mimeType"]
        teks = c.unduh_teks(f.id, mime, maks=3000)
    except Exception as e:
        return f"Gagal baca isi: {e}"
    if not teks.strip():
        return f"(Isi '{f.nama}' tak bisa diekstrak — kemungkinan gambar/scan.)"
    return f"📄 {f.nama}:\n{teks}"


@mcp.tool()
def usul_rename(nama_lama: str, nama_baru: str) -> str:
    """USUL mengganti nama file agar jelas & sesuai isi + konvensi — TIDAK langsung.

    Aksi ini MENGUBAH Drive → WAJIB persetujuan pengguna. Alur: baca isi
    (baca_dokumen) → panggil ini dengan nama baru → tunjukkan ke pengguna →
    HANYA setelah pengguna setuju ('ya'), panggil `jalankan_rename` dgn token.

    Konvensi nama: Title Case; DILARANG 'copy/copy of/final/fix/versi vN/(n)/
    test'; tanpa spasi ganda; pertahankan akronim (PT, NPWP, SK, PKWT…) &
    tanggal (YYYY-MM-DD). Nama HARUS mencerminkan ISI (jenis dokumen + pihak/
    subjek + tanggal bila relevan). Ekstensi lama dipertahankan otomatis.
    """
    import os as _os
    from app.kantor.dokumen import konsistensi as kons
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    kand = [x for x in c.cari(nama_lama, maks=25) if not x.is_folder and x.nama == nama_lama]
    if not kand:
        return f"File '{nama_lama}' tidak ditemukan (butuh nama persis)."
    if len(kand) > 1:
        return f"Ada {len(kand)} file bernama '{nama_lama}' — tak bisa dipastikan yang mana."
    f = kand[0]
    ext_lama = _os.path.splitext(f.nama)[1]
    if ext_lama and not _os.path.splitext(nama_baru)[1]:
        nama_baru = nama_baru + ext_lama  # jaga ekstensi
    if nama_baru == f.nama:
        return "Nama baru sama dengan nama lama — tak perlu diubah."
    h = kons.validasi_nama_file(nama_baru)
    err = [t.pesan for t in h.temuan if t.level == "error"]
    if err:
        return "❌ Nama usulan melanggar aturan: " + "; ".join(err) + ". Perbaiki dulu."
    warn = [t.pesan for t in h.temuan if t.level == "warning"]
    wln = ("\n⚠️ Catatan: " + "; ".join(warn)) if warn else ""
    tok = _token_rename(f.id, nama_baru)
    return (
        "📋 USUL RENAME (BELUM dijalankan):\n"
        f"• Dari : {f.nama}\n"
        f"• Jadi : {nama_baru}{wln}\n"
        "Minta persetujuan pengguna dulu. Setelah setuju ('ya'), panggil:\n"
        f"jalankan_rename(file_id='{f.id}', nama_baru='{nama_baru}', token='{tok}')"
    )


@mcp.tool()
async def jalankan_rename(file_id: str, nama_baru: str, token: str) -> str:
    """Eksekusi rename yang SUDAH disetujui pengguna (butuh token dari usul_rename).

    Reversible — nama lama disimpan di audit sehingga bisa dibalik. HANYA panggil
    setelah pengguna menyetujui usulan secara eksplisit.
    """
    if token != _token_rename(file_id, nama_baru):
        return ("❌ Token tidak cocok. Panggil usul_rename dulu, tunjukkan usulannya, "
                "baru jalankan setelah pengguna setuju.")
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    try:
        lama = c._service().files().get(
            fileId=file_id, fields="name", supportsAllDrives=True).execute()["name"]
        c.ganti_nama(file_id, nama_baru)
    except Exception as e:
        await _audit_kantor("rename_drive", file_id, {"jadi": nama_baru, "error": str(e)[:150]}, "gagal")
        return f"Gagal rename: {e}"
    await _audit_kantor("rename_drive", file_id, {"dari": lama, "jadi": nama_baru}, "sukses")
    return f"✅ Nama diubah: '{lama}' → '{nama_baru}'. (Reversible — nama lama tercatat di audit.)"


# ═══════════ Google Drive — BUAT DOKUMEN (.docx berkop → _TRANSIT draft) ═══════════
# Buat SEMUA jenis dokumen resmi (surat tugas/keterangan/SK/kontrak/perjanjian).
# Agent menyusun `isi`; tool membungkus dgn kop resmi identik template + simpan
# ke _TRANSIT sebagai DRAFT (sesuai aturan: file baru → transit + draft).
_MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _token_dokumen(judul: str, isi: str, extra: str = "") -> str:
    import hashlib
    import hmac as _hmac
    secret = os.environ.get("MCP_AUTH_TOKEN", "kantor").encode()
    return _hmac.new(secret, f"dok|{judul}|{isi}|{extra}".encode("utf-8"),
                     hashlib.sha256).hexdigest()[:10]


def _transit_folder_id(c):
    from app.kantor.drive import mapper, taksonomi as tx
    for f in c.anak():
        if f.is_folder and mapper.kode_kategori(f.nama) == tx.TRANSIT:
            return f.id
    return None


@mcp.tool()
def usul_buat_dokumen(
    judul: str, isi: str, nomor: str = "", nama_file: str = "",
    tembusan: str = "", tabel_json: str = "",
) -> str:
    """USUL membuat dokumen resmi (.docx berkop PT HMU) → simpan ke _TRANSIT DRAFT.

    Untuk SEMUA jenis: Surat Tugas, Surat Keterangan Kerja, SK, Kontrak Kerja
    PKWT/PKWTT, Surat Perjanjian, dll. Kamu (agent) menyusun `isi`; tool
    membungkus dgn kop resmi berwarna + tanda tangan Direktur Utama. TIDAK
    langsung dibuat — butuh persetujuan pengguna (alur usul → 'ya' → jalankan).

    Args:
        judul: judul dokumen (jadi judul berwarna di badan surat), mis. 'Surat Tugas'.
        isi: badan dokumen (multi-baris). Markup: baris '[[C]]Teks' = sub-judul
            tengah berwarna; baris '[[TABEL]]' = titik sisip tabel (isi via tabel_json).
        nomor: nomor surat resmi (opsional; via terbitkan_nomor_surat).
        nama_file: nama file tanpa ekstensi (opsional; default = judul).
        tembusan: daftar tembusan, pisah baris-baru atau ';' (opsional).
        tabel_json: JSON list-of-rows utk tabel, mis.
            '[["No","Nama","Jabatan"],["1","Budi","Sopir"]]' (baris-1 = header).
    """
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    if _transit_folder_id(c) is None:
        return "Folder _TRANSIT tidak ditemukan — tak bisa menyimpan draft."
    import json
    try:
        if tabel_json.strip():
            json.loads(tabel_json)
    except Exception as e:
        return f"tabel_json bukan JSON valid: {e}"
    fn = f"[DRAFT] {(nama_file or judul).strip()}.docx"
    cuplik = "\n".join(isi.strip().splitlines()[:6])
    tok = _token_dokumen(judul, isi, f"{tembusan}|{tabel_json}")
    return (
        "📋 USUL BUAT DOKUMEN (BELUM dibuat):\n"
        f"• Judul     : {judul}\n"
        f"• Nomor     : {nomor or '(tanpa nomor)'}\n"
        f"• Nama file : {fn}\n"
        f"• Lokasi    : _TRANSIT (status DRAFT)\n"
        f"• Tabel     : {'ya' if tabel_json.strip() else 'tidak'} · "
        f"Tembusan: {'ya' if tembusan.strip() else 'tidak'}\n"
        f"• Cuplikan isi:\n{cuplik}\n…\n"
        "Tunjukkan pratinjau ke pengguna. Setelah setuju ('ya'), panggil "
        "jalankan_buat_dokumen dengan judul/isi/nomor/nama_file/tembusan/"
        f"tabel_json SAMA + token='{tok}'."
    )


@mcp.tool()
async def jalankan_buat_dokumen(
    judul: str, isi: str, nomor: str = "", nama_file: str = "",
    tembusan: str = "", tabel_json: str = "", token: str = "",
) -> str:
    """Buat file .docx dokumen yang SUDAH disetujui pengguna (butuh token dari
    usul_buat_dokumen; argumen judul/isi/tembusan/tabel_json harus SAMA). File
    berkop resmi disimpan ke _TRANSIT sebagai DRAFT. HANYA setelah persetujuan.
    """
    if token != _token_dokumen(judul, isi, f"{tembusan}|{tabel_json}"):
        return "❌ Token tidak cocok. Panggil usul_buat_dokumen dulu + minta persetujuan pengguna."
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    tid = _transit_folder_id(c)
    if tid is None:
        return "Folder _TRANSIT tidak ditemukan."
    import json
    from app.kantor.dokumen import dok_docx
    tbs = [x.strip() for x in tembusan.replace(";", "\n").splitlines() if x.strip()] or None
    tbl = None
    if tabel_json.strip():
        try:
            tbl = json.loads(tabel_json)
        except Exception as e:
            return f"tabel_json bukan JSON valid: {e}"
    fn = f"[DRAFT] {(nama_file or judul).strip()}.docx"
    try:
        data = dok_docx.surat_docx(judul=judul, isi=isi, nomor=nomor,
                                   tembusan=tbs, tabel=tbl)
        c.buat_file(fn, data, _MIME_DOCX, tid)
    except Exception as e:
        await _audit_kantor("buat_dokumen", judul, {"error": str(e)[:150]}, "gagal")
        return f"Gagal membuat dokumen: {e}"
    await _audit_kantor("buat_dokumen", fn, {"judul": judul, "nomor": nomor}, "sukses")
    return (f"✅ Dokumen dibuat: '{fn}' di folder _TRANSIT (status DRAFT). "
            "Silakan tinjau; bila sudah final, hapus penanda [DRAFT] agar ikut diarsipkan.")


# ═══════════════ Google Drive — HAPUS (usul → konfirmasi; ke Sampah) ═══════════════
# 'Hapus' berpagar = pindah ke Trash Drive (reversible ~30 hari). BUKAN permanen.
def _token_hapus(file_id: str) -> str:
    import hashlib
    import hmac as _hmac
    secret = os.environ.get("MCP_AUTH_TOKEN", "kantor").encode()
    return _hmac.new(secret, f"hapus|{file_id}".encode(), hashlib.sha256).hexdigest()[:10]


@mcp.tool()
def usul_hapus_file(nama: str) -> str:
    """USUL menghapus file (→ Sampah Drive, reversible ~30 hari) — TIDAK langsung.

    Aksi konsekuensial → WAJIB persetujuan pengguna. Alur: panggil ini → tunjukkan
    file yang akan dihapus → HANYA setelah pengguna setuju ('ya') panggil
    `jalankan_hapus` dgn token. File masuk Sampah (bisa dipulihkan), bukan hapus
    permanen.

    Args:
        nama: nama file (persis) yang akan dihapus.
    """
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    kand = [x for x in c.cari(nama, maks=25) if not x.is_folder and x.nama == nama]
    if not kand:
        kand = [x for x in c.cari(nama, maks=25) if not x.is_folder]
    if not kand:
        return f"File '{nama}' tidak ditemukan."
    if len(kand) > 1:
        return "Beberapa file cocok — sebut nama persis:\n" + "\n".join(f"• {f.nama}" for f in kand[:10])
    f = kand[0]
    tok = _token_hapus(f.id)
    return (
        "📋 USUL HAPUS (BELUM dihapus):\n"
        f"• File : {f.nama}\n"
        "⚠️ Akan dipindah ke SAMPAH Drive (bisa dipulihkan ~30 hari, lalu terhapus "
        "otomatis). Minta persetujuan pengguna. Setelah setuju ('ya'), panggil:\n"
        f"jalankan_hapus(file_id='{f.id}', token='{tok}')"
    )


@mcp.tool()
async def jalankan_hapus(file_id: str, token: str) -> str:
    """Hapus file yang SUDAH disetujui pengguna → ke Sampah Drive (reversible ~30
    hari, bukan permanen). Butuh token dari usul_hapus_file. Dicatat di audit.
    HANYA panggil setelah pengguna setuju secara eksplisit.
    """
    if token != _token_hapus(file_id):
        return "❌ Token tidak cocok. Panggil usul_hapus_file dulu + minta persetujuan pengguna."
    c = _drive_client()
    if c is None:
        return _DRIVE_OFF
    try:
        nama = c._service().files().get(
            fileId=file_id, fields="name", supportsAllDrives=True).execute()["name"]
        c.buang_ke_sampah(file_id)
    except Exception as e:
        await _audit_kantor("hapus_drive", file_id, {"error": str(e)[:150]}, "gagal")
        return f"Gagal menghapus: {e}"
    await _audit_kantor("hapus_drive", file_id, {"nama": nama}, "sukses")
    return f"✅ '{nama}' dipindah ke Sampah Drive (bisa dipulihkan ~30 hari). Tercatat di audit."


# ─────────────────────────── Entry point ───────────────────────────
def _run_http() -> None:
    """Streamable-HTTP + gerbang token bearer (untuk agent remote spt Hermes)."""
    import uvicorn
    from starlette.types import ASGIApp, Receive, Scope, Send

    token = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "MCP_TRANSPORT=http butuh MCP_AUTH_TOKEN (token bearer). "
            "Set env itu dulu — jangan ekspos data pabrik tanpa autentikasi."
        )

    app = mcp.streamable_http_app()

    class BearerGate:
        """Tolak request tanpa 'Authorization: Bearer <token>' yang cocok."""

        def __init__(self, inner: ASGIApp) -> None:
            self.inner = inner

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http":
                # Healthcheck Railway (/health) TANPA token — bukan endpoint data.
                if scope.get("path") == "/health":
                    await send({"type": "http.response.start", "status": 200,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body",
                                "body": b'{"status":"ok","service":"mcp"}'})
                    return
                headers = dict(scope.get("headers") or [])
                auth = headers.get(b"authorization", b"").decode()
                if auth != f"Bearer {token}":
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [(b"content-type", b"text/plain")]})
                    await send({"type": "http.response.body", "body": b"unauthorized"})
                    return
            await self.inner(scope, receive, send)

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(BearerGate(app), host="0.0.0.0", port=port)


if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT", "stdio").lower() == "http":
        _run_http()
    else:
        mcp.run()
