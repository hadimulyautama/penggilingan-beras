-- Reset DATA TRANSAKSI (dummy) — kosongkan semua tabel operasional,
-- pertahankan data MASTER. Skema tidak diubah.
--
-- DIPERTAHANKAN (master): users, warehouses, silos, dryers, suppliers.
-- DIKOSONGKAN: pembelian, verifikasi, pengeringan, silo_storage, milling,
--              transfer, log aktivitas, notifikasi, dll.
--
-- Ingin supplier ikut dikosongkan juga? Hapus 'suppliers' dari daftar keep.
-- RESTART IDENTITY = reset penomoran id & (otomatis) kode harian GB/LOT/MIL.
DO $$
DECLARE
  r RECORD;
  keep text[] := ARRAY[
    'users', 'warehouses', 'silos', 'dryers', 'suppliers', 'alembic_version'
  ];
BEGIN
  FOR r IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND NOT (tablename = ANY(keep))
    ORDER BY tablename
  LOOP
    EXECUTE format('TRUNCATE TABLE public.%I RESTART IDENTITY CASCADE', r.tablename);
    RAISE NOTICE 'dikosongkan: %', r.tablename;
  END LOOP;
END $$;
