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
    # ── PALING ATAS, keputusan pemilik 26 September 2026 ──
    #
    # Permintaan lot PK dari Gudang 2 pindah ke layar ini dari Antrian tunggu.
    # Tempatnya memang di sini: yang ditunggu BUKAN pekerjaan fisik melainkan
    # keputusan — disetujui berapa, ke mana, atau ditolak dengan sebabnya.
    # Paling atas sebab ia menahan gudang sebelah: selama belum diputuskan,
    # mesin sosoh menunggu bahan yang sudah ada di gudang seberang.
    ("acc_permintaan_pk", "Permintaan lot PK dari Gudang 2", "permintaan"),
    # Yang sudah dikirim dan menunggu diakui angkanya. Tetap keputusan:
    # bobot Admin yang berlaku, dan barangnya sudah berpindah.
    ("tutup_permintaan_pk", "Kiriman PK menunggu ditutup", "permintaan"),
    # Dua baris harga DIBUANG 28 September 2026: harga keluar dari Pos Produksi
    # (keputusan pemilik). Golongan "harga" ikut kosong dengan sendirinya —
    # kalau kelak ada yang menambahkan jenis baru bergolongan itu, periksa
    # dulu apakah ia memang milik Pos Produksi.
    # "Output giling belum dicocokkan" DIHAPUS 24 September 2026, keputusan
    # pemilik: "yang mencatat hasil giling hanya operator. jika ada kesalahan
    # sudah ada di perbaiki hasil giling."
    #
    # Tagihannya yang hilang, bukan aksinya: `verify_output` tetap hidup sebagai
    # tombol "Perbaiki hasil giling" di kartu layar Stok — di situlah angkanya
    # dibaca, dan di situ pula ia dibetulkan. Yang berhenti adalah MENAGIH
    # admin mencocokkan tiap giling yang ditutup: angka operator kini angka
    # yang dipakai, bukan perkiraan yang menunggu disahkan.
    ("betulkan_bobot_giling", "Bobot masuk giling tak cocok", "output"),
    # ── CELAH YANG BARU KETAHUAN 2 Oktober 2026 ──
    #
    # Pemilik melaporkan sub-menu "Menunggu keputusan" tak muncul padahal ia
    # melihat DUA blok di layarnya — "Verifikasi Muatan" dan sesuatu lagi.
    # Diperiksa: `verifikasi_keluar` (muatan barang keluar Gudang 2 yang
    # menunggu diverifikasi Admin, lahir di `_kartu_barang_keluar`) TAK PERNAH
    # didaftarkan di sini. Fiturnya lahir 28 September 2026 (Barang Keluar),
    # SESUDAH daftar ini terakhir dianggap lengkap (24 September) — persis
    # pola yang sudah dicatat di kepala berkas ini untuk tiga jenis pertama:
    # "ada di data tetapi tak digambar di layar mana pun".
    #
    # Akibatnya BUKAN cuma kosmetik: tanpa baris ini, kartunya jatuh ke jaring
    # "Keputusan lain" — DAN ke keranjang "lain" sub-menu — bercampur dengan
    # jenis tak dikenal LAIN APA PUN. Dua jenis berbeda yang kebetulan
    # sama-sama jatuh ke "lain" terbaca sebagai SATU kategori, bukan dua —
    # dan itu yang membuat sub-menu (syaratnya ≥2 kategori) tak pernah
    # menawarkan dropdown walau layarnya sudah menunjukkan dua blok.
    #
    # Golongannya "output": ia memang pencocokan ATAS APA YANG KELUAR,
    # sejenis dengan `betulkan_bobot_giling` — dan Beranda yang menghitung
    # "N output" dari golongan ini pun sudah ikut salah-hitung sejak 28
    # September tanpa satu pun yang menyadarinya, sebab jumlahnya tak pernah
    # dibandingkan dengan lencana "Menunggu keputusan" yang total.
    ("verifikasi_keluar", "Muatan menunggu diverifikasi", "output"),
    ("qc_giling", "Mutu giling belum diperiksa", MUTU),
    ("qc_pk_luar", "Mutu PK luar belum dicatat", MUTU),
    ("qc_gabah_basah", "Mutu gabah basah belum dicatat", MUTU),
    ("qc_gabah_kering", "Mutu gabah kering belum dicatat", MUTU),
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
