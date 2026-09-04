"""Ikon layar utama Pos Produksi.

Bentuknya mengikuti ikon "Catat pekerjaan" di dalam aplikasi — rumah
penggilingan — supaya ikon di layar utama dan ikon di dalam aplikasi
berbicara tentang hal yang sama. Warnanya dari palet aplikasi itu sendiri.
"""
from PIL import Image, ImageDraw

DASAR = (22, 33, 42)      # --panel  #16212a
AKSI = (79, 179, 217)     # --aksi   #4fb3d9

# Gambar pada kanvas besar lalu diperkecil: tepi miring jadi halus tanpa
# perlu antialias garis, yang tidak dimiliki ImageDraw.
K = 2048
S = K / 512.0


def gambar() -> Image.Image:
    img = Image.new("RGBA", (K, K), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, K - 1, K - 1], radius=int(108 * S), fill=DASAR)

    # Bidang 24×24 dari ikon dalam aplikasi, dipetakan ke 96..416 dari 512.
    def t(x: float, y: float) -> tuple[float, float]:
        return (96 * S + x * (320 / 24) * S, 96 * S + y * (320 / 24) * S)

    w = int(26 * S)
    for titik in (
        [(4, 20), (4, 9), (12, 4), (20, 9), (20, 20)],   # atap & dinding
        [(4, 20), (20, 20)],                              # lantai
        [(10, 20), (10, 14), (14, 14), (14, 20)],         # pintu
    ):
        d.line([t(*p) for p in titik], fill=AKSI, width=w, joint="curve")
        for p in titik:                                   # ujung membulat
            x, y = t(*p)
            d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=AKSI)
    return img


besar = gambar()
for ukuran in (180, 192, 512):
    besar.resize((ukuran, ukuran), Image.LANCZOS).save(
        f"app/web/static/ikon-{ukuran}.png", optimize=True)
    print("ikon-%d.png" % ukuran)
