"""Identitas penerbit dokumen, mengikuti website/app.py: SITE dan logo perusahaan."""
from pathlib import Path

NAMA_PERUSAHAAN = 'PT HADI MULYA UTAMA'
ALAMAT = ('Kebayanan 1, Craken, Masaran',
          'Kabupaten Sragen, Jawa Tengah 57282')
KONTAK = 'Tel. +62 851-7416-7950  |  sales@hadimulya.com'
# Salinan aset resmi disertakan agar PDF tidak bergantung pada jaringan website.
LOGO = Path(__file__).with_name('static') / 'hmu-company-logo.png'
