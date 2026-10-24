"""Turunkan ikon pelanggan dari siluet logo PadiFlow yang sudah digunakan.

Latar polos oranye membedakan pemasangan portal. Kanal biru memisahkan
marka putih dari latar hijau master tanpa menggambar ulang huruf/daunnya.
"""
from pathlib import Path
from PIL import Image

AKAR = Path(__file__).resolve().parents[1]
with Image.open(AKAR / "hmu_tampilan/static/ikon-512.png") as sumber:
    siluet = sumber.convert("RGB").getchannel("B").point(
        lambda nilai: round(max(0, min(1, (nilai - 90) / 145)) * 255))
    master = Image.composite(Image.new("RGB", sumber.size, "#f4f2eb"),
                             Image.new("RGB", sumber.size, "#e87924"), siluet)
    for ukuran in (180, 192, 512):
        master.resize((ukuran, ukuran), Image.Resampling.LANCZOS).save(
            AKAR / f"app/web/static/pelanggan-ikon-{ukuran}.png", optimize=True)
