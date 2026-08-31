"""Sistem penggilingan beras — inti operasional pabrik.

Tiga domainnya:

  · `gudang1`  pembelian gabah, pengeringan, penyimpanan silo, penggilingan
  · `gudang2`  pembelian beras PK, polishing, hasil jadi
  · `inventory` barang jadi, pengemasan, pengeluaran

Dikumpulkan di bawah satu induk pada 31 Agustus 2026 supaya terlihat sebagai
SATU sistem. Sebelumnya ketiganya berdiri sejajar dengan `kantor` dan
`timbangan` di `app/`, sehingga dari susunan berkas tidak terbaca mana yang
satu produk dengan mana.

Yang sengaja TIDAK ikut turun ke sini, karena memang bukan milik penggilingan
saja: `app/ai` (lapisan agentik, dipakai kantor juga), `app/models` (fasad
model bersama), `app/bots` (kerangka bot yang dipakai kantor dan mini-app),
`app/services`, `app/web`, dan fondasi `config`/`database`. Menurunkannya ke
sini akan membuat tata letaknya berbohong.
"""
