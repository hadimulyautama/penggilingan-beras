"""Bukti timbang sebagai PDF, digambar di server.

**Mengapa tidak lewat dialog cetak browser.** Dua hal yang tidak bisa
dikendalikan dari HTML mana pun:

  · **Kop-kaki browser** — tanggal, jam, nomor halaman, dan URL halaman.
    Itu setelan dialog cetak, bukan bagian dokumen; CSS tidak bisa
    mematikannya. Di kertas nota resmi, URL aplikasi tidak punya tempat.
  · **Ukuran kertas** — `@page { size: ... }` hanya usulan. Yang menentukan
    adalah pilihan kertas di dialog, dan di ponsel dialog itu sering tidak
    menawarkan ukuran khusus sama sekali. Hasilnya A4, bukan setengah NCR.

Digambar di sini, ukurannya pasti dan halamannya bersih. Berkasnya bisa
dicetak maupun dibagikan lewat WhatsApp — keduanya dari satu berkas yang sama.

Seluruhnya MONOKROM: NCR adalah kertas berlapis karbon, lembar keduanya tidak
punya warna.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

from app.timbangan import format as fmt

# Setengah folio, melintang.
NCR_L, NCR_T = 215 * mm, 165 * mm
# Struk thermal: lebar kertas 80 mm, area cetak 72 mm. Tingginya menyesuaikan
# isi — PDF harus punya tinggi tetap, jadi dipakai angka yang cukup longgar.
STRUK_L = 72 * mm

TEBAL = "Helvetica-Bold"
BIASA = "Helvetica"


@dataclass
class Baris:
    label: str
    nilai: str
    jam: str = ""


def _potong(c, teks: str, font: str, ukuran: float, lebar: float) -> str:
    """Pangkas teks yang tidak muat, dengan elipsis — jangan sampai meluber."""
    if c.stringWidth(teks, font, ukuran) <= lebar:
        return teks
    while teks and c.stringWidth(teks + "…", font, ukuran) > lebar:
        teks = teks[:-1]
    return teks + "…"


def _isian(c, x, y, lebar, label, nilai, *, mono=False):
    """Label kecil di atas, nilai di atas garis — gaya buku nota."""
    c.setFont(TEBAL, 5.6)
    c.setFillGray(0.35)
    c.drawString(x, y + 4.2 * mm, label.upper())
    c.setFillGray(0)
    font = "Courier-Bold" if mono else BIASA
    c.setFont(font, 8.6)
    c.drawString(x, y + 1.3 * mm, _potong(c, nilai or "", font, 8.6, lebar))
    c.setLineWidth(0.5)
    c.setStrokeGray(0)
    c.line(x, y, x + lebar, y)


def bukti_ncr(*, trx, aturan, pihak: str, petugas: str, muatan,
              perusahaan: str, alamat: str, telepon: str,
              arah_masuk: bool) -> bytes:
    """Lembar setengah NCR 215 × 165 mm.

    Angka selisih TIDAK PERNAH digambar di sini, apa pun komoditasnya —
    keputusan Direksi 30 Agustus 2026. Lembar ini salinan untuk pihak luar,
    jadi hasil kontrol internal tidak ikut keluar. Perhatikan bahwa fungsi ini
    memang tidak menerima parameter selisih sama sekali: kerahasiaannya
    ditegakkan oleh ketiadaan jalan, bukan oleh percabangan yang bisa keliru.
    """
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(NCR_L, NCR_T))
    c.setTitle(trx.kode)

    M = 8 * mm                       # margin
    L = NCR_L - 2 * M                # lebar area
    atas = NCR_T - M

    # ── Kepala ──
    c.setFont(TEBAL, 13)
    c.drawString(M, atas - 4.6 * mm, perusahaan.upper())
    c.setFont(BIASA, 7.4)
    c.setFillGray(0.28)
    c.drawString(M, atas - 8.4 * mm, f"{alamat}  ·  {telepon}")
    c.setFillGray(0)

    # Nomor dalam kotak, di kanan atas
    kw, kh = 62 * mm, 11 * mm
    kx, ky = M + L - kw, atas - kh
    c.setLineWidth(1.2)
    c.rect(kx, ky, kw, kh)
    c.setFont(TEBAL, 5.6)
    c.setFillGray(0.35)
    c.drawString(kx + 2.5 * mm, ky + kh - 4.4 * mm, "NOMOR")
    c.setFillGray(0)
    c.setFont("Courier-Bold", 9.4)
    c.drawString(kx + 2.5 * mm, ky + 2.6 * mm, trx.kode)

    # ── Judul ──
    y = atas - 15 * mm
    c.setLineWidth(2)
    c.line(M, y, M + L, y)
    c.setFont(TEBAL, 10.5)
    judul = "BUKTI TIMBANG"
    c.drawCentredString(M + L / 2, y - 5.6 * mm, " ".join(judul))
    y -= 8.4 * mm
    c.setLineWidth(0.7)
    c.line(M, y, M + L, y)

    # ── Identitas: tiga kolom, gaya isian ──
    y -= 10 * mm
    lebar3 = 40 * mm                                  # kolom tanggal / nomor
    k1 = (L - 2 * 6 * mm - lebar3) / 2                # dua kolom pertama
    x1, x2, x3 = M, M + k1 + 6 * mm, M + L - lebar3

    _isian(c, x1, y, k1, "Pengirim" if arah_masuk else "Tujuan", pihak)
    _isian(c, x2, y, k1, "Barang", aturan.nama)
    _isian(c, x3, y, lebar3, "Tanggal",
           trx.tanggal.strftime("%d-%m-%Y"), mono=True)

    y -= 11 * mm
    _isian(c, x1, y, k1, "Nomor polisi", trx.nomor_polisi or "", mono=True)
    _isian(c, x2, y, k1, "Sopir", trx.nama_sopir or "")
    _isian(c, x3, y, lebar3, "Nota" if arah_masuk else "Surat jalan",
           (muatan[0].nomor_acuan if muatan else "") or "", mono=True)

    # ── Tabel angka ──
    y -= 13 * mm
    tabel_l = L - 66 * mm            # sisakan ruang tanda tangan di kanan
    for b in _baris_angka(trx, arah_masuk):
        y -= 7.4 * mm
        c.setFont(BIASA, 8.2)
        c.setFillGray(0)
        c.drawString(M, y, b.label)
        if b.jam:
            lb = c.stringWidth(b.label, BIASA, 8.2)
            c.setFont("Courier", 6.4)
            c.setFillGray(0.45)
            c.drawString(M + lb + 1.6 * mm, y, b.jam)
            c.setFillGray(0)
        c.setFont("Courier", 8.6)
        c.drawRightString(M + tabel_l, y, b.nilai)
        c.setLineWidth(0.3)
        c.setStrokeGray(0.8)
        c.line(M, y - 1.8 * mm, M + tabel_l, y - 1.8 * mm)

    # Berat barang — angka yang dicari orang
    y -= 5.4 * mm
    c.setLineWidth(1.2)
    c.setStrokeGray(0)
    c.line(M, y, M + tabel_l, y)
    y -= 8.4 * mm
    c.setFont(TEBAL, 9.6)
    c.drawString(M, y, "BERAT BARANG")
    c.setFont("Courier-Bold", 14.5)
    c.drawRightString(M + tabel_l, y - 0.6 * mm,
                      f"{fmt.angka(trx.berat_barang_kg)} kg")

    y_berat = y

    # ── Catatan ──
    y -= 13 * mm
    _isian(c, M, y, tabel_l, "Catatan",
           _potong(c, trx.catatan or "", BIASA, 8.6, tabel_l))

    # ── Tanda tangan: mengisi ruang di kanan tabel, sejajar angka utama,
    #    bukan terdampar di kaki halaman.
    tx = M + tabel_l + 10 * mm
    lebar_ttd = (M + L - tx - 6 * mm) / 2
    ty = M + 17 * mm
    c.setFont(BIASA, 5.8)
    c.setFillGray(0.42)
    c.drawString(tx, ty + 22 * mm,
                 "Ditandatangani kedua pihak sebagai bukti")
    c.setFillGray(0)
    for i, (label, nama) in enumerate((("Petugas timbang", petugas),
                                       ("Sopir (saksi)", trx.nama_sopir or ""))):
        x = tx + i * (lebar_ttd + 6 * mm)
        c.setFont(TEBAL, 5.6)
        c.setFillGray(0.35)
        c.drawCentredString(x + lebar_ttd / 2, ty + 17 * mm, label.upper())
        c.setFillGray(0)
        c.setLineWidth(0.5)
        c.setStrokeGray(0)
        c.line(x, ty, x + lebar_ttd, ty)
        c.setFont(BIASA, 7.4)
        c.drawCentredString(x + lebar_ttd / 2, ty - 3.6 * mm,
                            _potong(c, nama, BIASA, 7.4, lebar_ttd))

    # ── Kaki ──
    #
    # SENGAJA tanpa tanggal, jam, nomor halaman, maupun URL. Kertas nota yang
    # diterima pengirim tidak perlu memuat jejak alat yang membuatnya; kapan
    # lembar ini dicetak sudah tercatat di jejak audit, tempatnya memang di
    # sana. Ini pula alasan PDF-nya digambar di server: kop-kaki browser tidak
    # bisa dimatikan dari HTML.
    c.setLineWidth(0.4)
    c.setStrokeGray(0.6)
    c.line(M, M + 5 * mm, M + L, M + 5 * mm)
    c.setFont(BIASA, 5.8)
    c.setFillGray(0.42)
    c.drawString(M, M + 1.8 * mm,
                 f"Lembar 1 — {'Pengirim' if arah_masuk else 'Pembeli'}"
                 f"   ·   Lembar 2 — Arsip pos timbang")

    c.showPage()
    c.save()
    return buf.getvalue()


def _baris_angka(trx, arah_masuk: bool) -> list[Baris]:
    b = [Baris("Bruto — truk bermuatan",
               f"{fmt.angka(trx.berat_bermuatan_kg)} kg",
               fmt.jam(trx.timbang1_waktu if arah_masuk else trx.timbang2_waktu))]
    if trx.berat_kosong_kg is not None:
        b.append(Baris(
            f"Tara truk — {'setelah bongkar' if arah_masuk else 'sebelum muat'}",
            f"{fmt.angka(trx.berat_kosong_kg)} kg",
            fmt.jam(trx.timbang2_waktu if arah_masuk else trx.timbang1_waktu)))
    b.append(Baris("Netto timbangan", f"{fmt.angka(trx.netto_timbangan_kg)} kg"))
    if trx.jumlah_karung:
        per = float(trx.total_tara_kg or 0) / trx.jumlah_karung
        b.append(Baris(
            f"Tara karung  {trx.jumlah_karung} × {fmt.angka(per, 3)} kg",
            f"- {fmt.angka(trx.total_tara_kg, 2)} kg"))
    if trx.tara_lain_kg:
        b.append(Baris("Tara lain", f"- {fmt.angka(trx.tara_lain_kg, 2)} kg"))
    return b


def bukti_thermal(*, trx, aturan, pihak: str, petugas: str, muatan,
                  perusahaan: str, alamat: str, telepon: str,
                  arah_masuk: bool, tampilkan_selisih: bool) -> bytes:
    """Struk 80 mm (area cetak 72 mm), tinggi menyesuaikan isi.

    Berbeda dari lembar NCR, struk ini MASIH mengikuti aturan per komoditas:
    gabah tanpa selisih (SOP butir 8), beras PK dengan selisih (Sistem Tara
    butir 9). Karena itu ia menerima `tampilkan_selisih`.
    """
    baris = _baris_angka(trx, arah_masuk)
    tinggi = (58 + 5.2 * len(baris) + (14 if tampilkan_selisih else 0)
              + (8 if trx.catatan else 0) + 28) * mm

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(STRUK_L, tinggi))
    c.setTitle(trx.kode)
    M = 4 * mm
    L = STRUK_L - 2 * M
    y = tinggi - M

    def tengah(teks, font, ukuran, turun):
        nonlocal y
        y -= turun
        c.setFont(font, ukuran)
        c.drawCentredString(STRUK_L / 2, y, teks)

    def pasang(kiri, kanan, turun=4.4 * mm, tebal=False):
        nonlocal y
        y -= turun
        c.setFont(TEBAL if tebal else BIASA, 7.4)
        c.drawString(M, y, kiri)
        c.setFont("Courier-Bold" if tebal else "Courier", 7.6)
        c.drawRightString(M + L, y, kanan)

    def garis(putus=True):
        nonlocal y
        y -= 2.4 * mm
        c.setLineWidth(0.4)
        c.setDash(1, 2) if putus else c.setDash()
        c.line(M, y, M + L, y)
        c.setDash()

    tengah(perusahaan, TEBAL, 9.4, 5 * mm)
    tengah(alamat, BIASA, 6.6, 3.6 * mm)
    tengah(telepon, BIASA, 6.6, 3.2 * mm)
    garis()
    tengah("B U K T I   T I M B A N G", TEBAL, 7.6, 5 * mm)
    garis()

    pasang("No.", trx.kode)
    pasang("Tanggal", trx.tanggal.strftime("%d-%m-%Y"))
    pasang("Pengirim" if arah_masuk else "Pihak", _potong(c, pihak, "Courier", 7.6, 40 * mm))
    pasang("Nomor polisi", trx.nomor_polisi or "-")
    if trx.nama_sopir:
        pasang("Sopir", _potong(c, trx.nama_sopir, "Courier", 7.6, 40 * mm))
    pasang("Barang", _potong(c, aturan.nama, "Courier", 7.6, 40 * mm))
    if muatan and muatan[0].nomor_acuan:
        pasang("Nota" if arah_masuk else "Surat jalan", muatan[0].nomor_acuan)
    garis()

    for b in baris:
        pasang(b.label + (f" {b.jam}" if b.jam else ""), b.nilai)
    garis(putus=False)
    pasang("BERAT BARANG", f"{fmt.angka(trx.berat_barang_kg)} kg",
           turun=5.6 * mm, tebal=True)

    if tampilkan_selisih:
        garis()
        pasang("Menurut dokumen", f"{fmt.angka(trx.berat_acuan_kg)} kg")
        pasang("Selisih", fmt.kg_tanda(trx.selisih_kg, 2))

    if trx.catatan:
        garis()
        y -= 4 * mm
        c.setFont(BIASA, 6.6)
        c.drawString(M, y, _potong(c, trx.catatan, BIASA, 6.6, L))

    # Tanda tangan
    y -= 12 * mm
    for i, (label, nama) in enumerate((("Petugas timbang", petugas),
                                       ("Sopir (saksi)", trx.nama_sopir or ""))):
        x = M + i * (L / 2)
        c.setFont(BIASA, 6.2)
        c.drawCentredString(x + L / 4, y + 9 * mm, label)
        c.setLineWidth(0.4)
        c.line(x + 2 * mm, y, x + L / 2 - 2 * mm, y)
        c.setFont(BIASA, 6.2)
        c.drawCentredString(x + L / 4, y - 3.4 * mm,
                            _potong(c, nama, BIASA, 6.2, L / 2 - 4 * mm))

    y -= 8 * mm
    c.setFont(BIASA, 5.8)
    c.setFillGray(0.42)
    c.drawCentredString(STRUK_L / 2, y,
                        "Ditandatangani kedua pihak sebagai bukti")

    c.showPage()
    c.save()
    return buf.getvalue()
