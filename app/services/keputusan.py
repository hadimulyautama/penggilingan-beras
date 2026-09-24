"""Jenis pekerjaan MEJA — daftarnya, judulnya, dan golongannya. Satu tempat.

Ada enam jenis pekerjaan yang tertahan di meja, dan sejak 24 September 2026
mereka digambar di DUA layar: "Menunggu keputusan" (`/keputusan`) untuk uang
dan pencocokan, "Mutu & QC" (`/mutu`) untuk mutu. Pemisahannya permintaan
pemilik.

**Kenapa daftarnya di sini, dan bukan di kedua layar itu.** Sampai 23 September
2026 daftar blok hidup di dalam templat `keputusan.html`, dan isinya TIGA dari
enam jenis yang `berjalan.untuk()` sungguh kirim — harga PK luar, mutu PK luar,
dan pembetulan bobot giling ada di data tetapi tak digambar di layar mana pun.
Pekerjaan yang menahan uang, tak tertagih, tanpa satu pun tanda. Kalimat yang
ditulis saat itu masih berlaku, dan sekarang berlaku dua kali lipat:

    Templat yang memegang daftarnya sendiri tak bisa tahu ia ketinggalan.

Dua layar yang masing-masing memegang separuh daftar punya penyakit yang sama,
dan lebih buruk: jenis yang lahir nanti bisa muncul di KEDUANYA (kalau tiap
layar hanya menolak daftarnya sendiri) atau TAK DI MANA PUN (kalau tiap layar
hanya menyaring daftarnya sendiri). Karena itu di sini ada satu tupel, dan
kedua layar — juga lencana, juga Beranda — menurunkan isinya dari situ.

Golongannya bukan hiasan: Beranda menyebut "N harga · N output" dan sebuah
pintu mutu tersendiri, dan angka yang tak berjumlah sama dengan lencananya
membuat orang berhenti mempercayai keduanya.
"""
from __future__ import annotations

#: Golongan mutu — pekerjaan yang pindah ke layar "Mutu & QC".
MUTU = "mutu"

#: (id aksi, judul blok, golongan), BERURUT.
#:
#: Urutannya mengikuti uang yang tertahan paling lama: harga lebih dulu, lalu
#: pencocokan output. Pembetulan bobot terakhir — ia perbaikan atas keadaan
#: yang jarang, bukan pekerjaan harian, dan bobot yang tak cocok membuat
#: rendemen & HPP salah sampai dibetulkan.
#:
#: Menambah jenis ketujuh = menambah satu baris di sini. Layar, lencana,
#: Beranda, dan jaring penangkapnya ikut sendiri.
JENIS: tuple[tuple[str, str, str], ...] = (
    ("verify_gabah", "Harga gabah belum diverifikasi", "harga"),
    ("harga_pk_luar", "Harga PK luar belum diverifikasi", "harga"),
    ("verify_output", "Output giling belum dicocokkan", "output"),
    ("betulkan_bobot_giling", "Bobot masuk giling tak cocok", "output"),
    ("qc_giling", "Mutu giling belum diperiksa", MUTU),
    ("qc_pk_luar", "Mutu PK luar belum dicatat", MUTU),
)

#: Seluruh id yang sudah punya bloknya sendiri — GABUNGAN kedua layar.
#:
#: Dipakai satu jaring penangkap, dan jaring itu tinggal di `/keputusan` saja:
#: dua jaring yang masing-masing menolak daftarnya sendiri akan menggambar
#: jenis ketujuh DUA KALI.
SEMUA: tuple[str, ...] = tuple(a for a, _, _ in JENIS)

#: Golongan → id-idnya. Dibaca Beranda ("N harga · N output") dan lencana.
GOLONGAN: dict[str, tuple[str, ...]] = {
    g: tuple(a for a, _, gg in JENIS if gg == g) for _, _, g in JENIS
}

#: Id golongan mutu, untuk penyaring yang dipakai berulang.
AKSI_MUTU: tuple[str, ...] = GOLONGAN[MUTU]


def blok(mutu: bool) -> tuple[tuple[str, str], ...]:
    """(id, judul) untuk satu layar. `mutu=True` → layar Mutu & QC."""
    return tuple((a, j) for a, j, g in JENIS if (g == MUTU) is mutu)


def golongan_mutu(aksi: str | None) -> bool:
    """Apakah pekerjaan ini milik layar Mutu & QC."""
    return (aksi or "") in AKSI_MUTU
