"""Aksi yang dibuka DARI KARTU tak boleh menuntut orangnya mengetik.

Laporan pemilik 26 September 2026, dengan fotonya: menekan "Minta lot ini" di
kartu lot LOT-20260926-03 membuka borang berisi kotak kosong bertuliskan
"LOT PK" dan papan ketik naik. "kalau harus mengetik lot tentu sangat repot."

SEBABNYA satu baris di `aksi.js` yang mudah dilewatkan: penguncian-dari-kartu
hanya berlaku untuk isian bertipe PILIHAN —

    if (f0.type !== "select" && f0.type !== "remote"
        && f0.type !== "remote_banyak") { continue; }

— jadi kartu memang mengirim `?buka=…&nilai=…`, dan isian bertipe `text`
mengabaikannya. Spesifikasinya sendiri menulis alasan yang meyakinkan ("ia
SELALU dibuka dari kartu, yang sudah menyebut lot mana") dan alasan itu justru
yang membuatnya salah: karena dianggap selalu terisi dari kartu, tak ada yang
memeriksa apakah kartu benar-benar bisa mengisinya.

Lima aksi rantai permintaan PK kena sekaligus. Tiga di antaranya milik Admin
dan meminta `permintaan` — ID BARIS BASIS DATA, angka yang tak pernah
ditampilkan di layar mana pun. Tak ada cara mengetahuinya selain menebak.

Pagar ini menjaga aturannya, bukan kelima aksi itu: APA PUN aksi yang dirujuk
sebuah kartu, isian pertamanya harus bertipe yang bisa dikunci `aksi.js`.
"""
from __future__ import annotations

import pathlib
import re

AKAR = pathlib.Path(__file__).resolve().parents[1]

#: Tipe yang `aksi.js` bisa isi & kunci dari `nilai` kartu. Daftar ini SALINAN
#: dari cabang di `bukaAksi`; kalau di sana bertambah, di sini juga —
#: `test_daftar_tipe_ini_sama_dengan_aksi_js` di bawah yang menagihnya.
BISA_DIKUNCI = ("select", "remote", "remote_banyak")


def _spesifikasi() -> dict[str, tuple[str, str]]:
    """{id aksi: (nama medan pertama, tipenya)} dari katalog `api.py`."""
    s = (AKAR / "app/web/api.py").read_text()
    keluar: dict[str, tuple[str, str]] = {}
    for m in re.finditer(r'\{"id": "([a-z0-9_]+)", "label": "', s):
        i = s.find('"fields"', m.end())
        if i < 0 or i - m.end() > 2000:
            continue
        j = s.find('{"name"', i)
        if j < 0:
            continue
        medan = s[j:s.find("},", j) + 1]
        nama = re.search(r'"name": "([a-z0-9_]+)"', medan)
        tipe = re.search(r'"type": "([a-z_]+)"', medan)
        if nama and tipe:
            keluar[m.group(1)] = (nama.group(1), tipe.group(1))
    return keluar


def _aksi_dari_kartu() -> set[str]:
    """Aksi yang dirujuk kartu — lewat `aksi=` maupun daftar `pilihan`.

    Keduanya membuka lembar dengan `nilai` kartunya, jadi keduanya menjanjikan
    hal yang sama kepada orang yang menekannya: benda yang sudah ia tunjuk tak
    akan ditanyakan lagi.
    """
    s = (AKAR / "app/services/berjalan.py").read_text()
    aksi = set(re.findall(r'aksi="([a-z0-9_]+)"', s))
    aksi |= set(re.findall(r'pilihan=\[\("([a-z0-9_]+)"', s))
    aksi |= set(re.findall(r'\n\s*\("([a-z0-9_]+)", "[^"]+",\s*\n?\s*"[^"]*",\s*', s))
    return {a for a in aksi if a}


def test_aksi_yang_dibuka_dari_kartu_tak_menuntut_ketikan():
    spek = _spesifikasi()
    salah = []
    for aksi in sorted(_aksi_dari_kartu()):
        if aksi not in spek:
            continue                      # bukan aksi berkatalog (mis. undo)
        nama, tipe = spek[aksi]
        if tipe not in BISA_DIKUNCI:
            salah.append(f"{aksi}: medan pertama '{nama}' bertipe '{tipe}' — "
                         "kartu mengirim nilainya, borang mengabaikannya")
    assert not salah, (
        "aksi ini dibuka dari kartu tetapi isian penunjuknya tak bisa diisi "
        "kartu:\n  " + "\n  ".join(salah))


def test_rantai_permintaan_pk_seluruhnya_bisa_ditekan_bukan_diketik():
    """Kelima aksi rantai itu disebut satu per satu, bukan disandarkan pada
    pagar di atas.

    Sebabnya: pagar di atas berangkat dari kartu yang ADA hari ini. Kartu bisa
    hilang atau berganti nama, dan saat itu terjadi kelima aksi ini akan lolos
    tanpa diperiksa — padahal yang membuat pemilik memotret layarnya justru
    aksi-aksi ini. Tiga di antaranya meminta ID BARIS, angka yang tak pernah
    ditampilkan di layar mana pun.
    """
    spek = _spesifikasi()
    for aksi in ("minta_pk_g1", "kirim_permintaan_pk", "acc_permintaan_pk",
                 "tolak_permintaan_pk", "tutup_permintaan_pk"):
        nama, tipe = spek[aksi]
        assert tipe in BISA_DIKUNCI, f"{aksi} kembali menuntut ketikan ({tipe})"


def test_tiap_daftar_jarak_jauh_punya_rutenya():
    """Sumber yang salah ketik tak melahirkan galat: daftarnya cuma kosong, dan
    yang terbaca orang adalah "tidak ada yang bisa dipilih"."""
    s = (AKAR / "app/web/api.py").read_text()
    rute = set(re.findall(r'@router\.get\("(/actions/[a-z0-9\-/]+)"\)', s))
    from urllib.parse import urlsplit
    hilang = [src for src in set(re.findall(r'"source": "/api(/actions/[^"]+)"', s))
              if urlsplit(src).path not in rute]
    assert not hilang, f"sumber daftar tanpa rute: {hilang}"


def test_daftar_tipe_ini_sama_dengan_aksi_js():
    """`BISA_DIKUNCI` di atas salinan dari `aksi.js`. Salinan yang diam-diam
    berbeda membuat pagar ini meluluskan aksi yang sebenarnya tak bisa
    dikunci — pagar yang salah lebih buruk daripada tak ada pagar."""
    js = (AKAR / "hmu_tampilan/static/aksi.js").read_text()
    i = js.index("function bukaAksi")
    potongan = js[i:i + 2000]
    tipe = set(re.findall(r'f0\.type !== "([a-z_]+)"', potongan))
    assert tipe == set(BISA_DIKUNCI), (
        f"aksi.js mengunci {sorted(tipe)}, pagar ini menyangka "
        f"{sorted(BISA_DIKUNCI)}")
