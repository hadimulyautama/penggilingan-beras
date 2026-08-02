"""Otak perusahaan — ingest SOP/pedoman → potong → simpan → cari.

  - chunker.py  : potong dokumen jadi bagian (murni, teruji)
  - ingest.py   : simpan dokumen + potongannya ke DB (dedup via hash)
  - retrieve.py : cari potongan relevan untuk konteks peran

Fase awal memakai pencarian kata (Postgres full-text) — gratis, tanpa model,
langsung jalan. Pencarian makna (embedding) menyusul sebagai peningkatan.
"""
