"""Turunkan ukuran ikon dari master PadiFlow yang telah disetujui."""
from pathlib import Path
from PIL import Image

STATIC = Path(__file__).resolve().parents[1] / 'hmu_tampilan/static'
with Image.open(STATIC/'padiflow-icon-master.png') as master:
    for size in (180, 192, 512):
        master.resize((size, size), Image.Resampling.LANCZOS).save(STATIC/f'ikon-{size}.png', optimize=True)
