"""Berapa baris `pelanggan` yang BELUM tertaut Kledo (kledo_contact_id
kosong), dan masih dipakai transaksi di mana saja — sebelum memutuskan apa
pun soal membersihkannya.

Permintaan pemilik 4 Oktober 2026: "selain kontak yang ada di kledo,
bersihkan dari database." Sebelum menghapus apa pun, pertanyaannya dijawab
dulu dengan angka sungguhan — bukan ditebak dari membaca skema.

**READ-ONLY.** Hanya `SELECT`; tak ada satu baris pun yang diubah atau
dihapus. Aman dijalankan langsung terhadap basis data produksi.

Dijalankan DENGAN environment Railway produksi (`DATABASE_URL`-nya),
supaya yang dihitung adalah basis data sungguhan, bukan salinan lokal:

    railway run --service penggilingan-beras \\
        .venv/bin/python scripts/laporan_pelanggan_non_kledo.py

Nilai `DATABASE_URL` tidak pernah dibaca atau dicetak oleh skrip ini — ia
cuma dipakai `app.database.SessionLocal`, yang sudah membacanya sendiri
lewat `app.config.settings` seperti aplikasi sehari-hari. Railway yang
menyuntikkannya ke proses; skrip ini tak pernah menyentuhnya langsung.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.database import SessionLocal

T = "\033[1m"
N = "\033[0m"


async def main() -> None:
    async with SessionLocal() as db:
        total = (await db.execute(text(
            "SELECT count(*) FROM pelanggan"
        ))).scalar_one()
        tanpa_kledo = (await db.execute(text(
            "SELECT count(*) FROM pelanggan WHERE kledo_contact_id IS NULL"
        ))).scalar_one()

        print(f"{T}Total baris di pelanggan:{N} {total}")
        print(f"{T}Tanpa kledo_contact_id (kandidat dibersihkan):{N} {tanpa_kledo}")

        if tanpa_kledo == 0:
            print("\nTidak ada yang perlu dibersihkan.")
            return

        # ── Tabel APA SAJA yang bertaut ke pelanggan(id) — DINAMIS ──
        #
        # Dibaca dari katalog Postgres sendiri, bukan daftar hafalan: tabel
        # baru yang kelak menunjuk pelanggan ikut terperiksa otomatis, tak
        # perlu ada yang ingat memperbarui skrip ini.
        fk = (await db.execute(text("""
            SELECT tc.table_name, kcu.column_name
              FROM information_schema.table_constraints tc
              JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
              JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
               AND tc.table_schema = ccu.table_schema
             WHERE tc.constraint_type = 'FOREIGN KEY'
               AND ccu.table_name = 'pelanggan'
               AND ccu.column_name = 'id'
             ORDER BY tc.table_name
        """))).all()

        print(f"\n{T}Dipakai lewat foreign key:{N}")
        if not fk:
            print("  (tak ada — tapi periksa manual kolom NAMA BEBAS yang "
                  "kebetulan mirip, mis. outgoing_records.nama_pembeli; "
                  "kolom begitu tak terlihat di sini karena bukan foreign key.)")
        for tabel, kolom in fk:
            n = (await db.execute(text(
                f'SELECT count(*) FROM "{tabel}" t '
                f'JOIN pelanggan p ON p.id = t."{kolom}" '
                f"WHERE p.kledo_contact_id IS NULL"
            ))).scalar_one()
            tanda = " ⚠ MASIH DIPAKAI" if n else ""
            print(f"  · {tabel}.{kolom}: {n} baris{tanda}")

        print(f"\n{T}Lima contoh terbaru (tanpa kledo_contact_id):{N}")
        contoh = (await db.execute(text(
            "SELECT id, nama_pelanggan, created_at FROM pelanggan "
            "WHERE kledo_contact_id IS NULL "
            "ORDER BY created_at DESC NULLS LAST LIMIT 5"
        ))).all()
        for baris in contoh:
            print(f"  · #{baris[0]}: {baris[1]} (dibuat {baris[2]})")


if __name__ == "__main__":
    asyncio.run(main())
