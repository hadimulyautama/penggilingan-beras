"""Modul Timbangan Gabah — webapp internal (browser) untuk input, kontrol, dan
monitoring transaksi pembelian gabah.

Mandiri secara kode (tabel `timbangan_*`, login sendiri, UI sendiri), namun
menumpang fondasi yang sudah ada: satu service Railway, satu PostgreSQL, master
`suppliers` & `users` yang sama. Jembatan integrasi ke pabrik sudah disiapkan
lewat kolom `timbangan_transaksi.purchase_batch_id` (kini dibiarkan kosong).
"""
