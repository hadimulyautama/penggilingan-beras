"""Pendeteksi masalah arsip dari Snapshot — menegakkan Pedoman Kearsipan.

Menghasilkan daftar Temuan + usulan tindakan (pindah/rename). MURNI atas
Snapshot (data dari mapper). Belum mengeksekusi apa pun — eksekusi (mode auto)
dilakukan lapisan lain setelah/tanpa approval sesuai kebijakan.

Jenis temuan:
  - nyasar   : file menganggur di root (bukan di kategori mana pun) → usul kategori
  - sortir   : file di _TRANSIT menunggu disposisi → usul kategori
  - nama     : nama file melanggar konvensi → usul nama baku
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.kantor.dokumen import konsistensi as kons
from app.kantor.drive import taksonomi as tx
from app.kantor.drive.mapper import Snapshot


@dataclass
class Temuan:
    jenis: str                 # nyasar / sortir / nama
    file_id: str
    nama: str
    lokasi: str                # breadcrumb induk
    usul: str                  # tindakan yang disarankan (bahasa manusia)
    kategori_usul: str | None = None   # kode kategori tujuan (bila ada)
    nama_usul: str | None = None       # nama baku (bila perlu rename)


@dataclass
class Laporan:
    nyasar: list[Temuan] = field(default_factory=list)       # menganggur di root
    salah_tempat: list[Temuan] = field(default_factory=list)  # di kategori yang salah
    sortir: list[Temuan] = field(default_factory=list)       # menunggu di _TRANSIT
    nama: list[Temuan] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (len(self.nyasar) + len(self.salah_tempat)
                + len(self.sortir) + len(self.nama))


def _usul_kategori(nama: str, jalur: str) -> tuple[str | None, str]:
    """Tebak kategori tujuan → (kode, teks usul)."""
    tebak = tx.tebak_kategori(nama, jalur)
    if not tebak:
        return None, "perlu dibaca isinya dulu (dibantu AI)"
    kode = tebak[0][0]
    kat = tx.kategori(kode)
    return kode, f"pindah ke {kode} - {kat.nama}" if kat else "perlu dicek"


def audit(snap: Snapshot) -> Laporan:
    """Analisa snapshot → Laporan temuan + usulan."""
    lap = Laporan()
    for e in snap.files:
        # 1) lokasi: nyasar di root / menunggu _TRANSIT / salah kategori
        if e.kategori is None:
            kode, usul = _usul_kategori(e.nama, e.jalur)
            lap.nyasar.append(Temuan("nyasar", e.id, e.nama, "root (menganggur)",
                                     usul, kategori_usul=kode))
        elif e.kategori == tx.TRANSIT:
            kode, usul = _usul_kategori(e.nama, e.jalur)
            lap.sortir.append(Temuan("sortir", e.id, e.nama, "_TRANSIT",
                                     usul, kategori_usul=kode))
        elif e.kategori != tx.ARSIP_LAMA:
            # di kategori nyata → cek apakah isinya lebih cocok kategori lain
            skor = tx.tebak_kategori(e.nama, e.jalur)
            if skor:
                top_kode, top_n = skor[0]
                skor_sekarang = next((n for k, n in skor if k == e.kategori), 0)
                # kategori lain menang telak (>skor kategori sekarang) → mungkin salah tempat
                if top_kode != e.kategori and top_n > skor_sekarang:
                    kat = tx.kategori(top_kode)
                    lap.salah_tempat.append(Temuan(
                        "salah_tempat", e.id, e.nama,
                        f"{e.kategori} (sekarang)", f"mungkin pindah ke {top_kode} - {kat.nama}"
                        if kat else "cek ulang", kategori_usul=top_kode))

        # 2) nama file melanggar konvensi (error-level saja → hindari bising)
        hasil = kons.validasi_nama_file(e.nama)
        if any(t.level == "error" for t in hasil.temuan) and hasil.nama_usulan:
            lap.nama.append(Temuan("nama", e.id, e.nama, e.jalur or "root",
                                   f"ganti nama → {hasil.nama_usulan}",
                                   nama_usul=hasil.nama_usulan))
    return lap


def ringkas(lap: Laporan) -> str:
    """Laporan → teks ringkas siap kirim ke pemilik (Telegram/log)."""
    baris = [f"🗂️ Audit arsip: {lap.total} temuan.\n"]
    if lap.nyasar:
        baris.append(f"📌 {len(lap.nyasar)} file nyasar di root:")
        baris += [f"   • {t.nama} → {t.usul}" for t in lap.nyasar[:15]]
    if lap.salah_tempat:
        baris.append(f"\n🔀 {len(lap.salah_tempat)} file mungkin SALAH KATEGORI:")
        baris += [f"   • {t.nama}  [{t.lokasi}] → {t.usul}"
                  for t in lap.salah_tempat[:25]]
    if lap.sortir:
        baris.append(f"\n📥 {len(lap.sortir)} file di _TRANSIT menunggu disortir:")
        baris += [f"   • {t.nama} → {t.usul}" for t in lap.sortir[:15]]
    if lap.nama:
        baris.append(f"\n✏️ {len(lap.nama)} nama file perlu dirapikan:")
        baris += [f"   • {t.nama} → {t.nama_usul}" for t in lap.nama[:15]]
    if lap.total == 0:
        baris.append("✅ Rapi — tak ada temuan.")
    return "\n".join(baris)
