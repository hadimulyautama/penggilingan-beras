-- Perbaikan: 1 dryer hanya boleh berisi 1 lot.
-- Gabungkan SEMUA lot berstatus 'proses' (yang di dryer) menjadi SATU lot
-- (yang tertua / id terkecil). Batch & log dari lot lain dipindahkan, lalu
-- lot ekstra dihapus. Aman dijalankan berulang (idempoten).
--
-- Jalankan sekali di Railway: service Postgres -> tab Data / query, tempel ini.
DO $$
DECLARE
  keep_id int;
  extra   RECORD;
BEGIN
  SELECT id INTO keep_id FROM drying_lots WHERE status = 'proses' ORDER BY id LIMIT 1;
  IF keep_id IS NULL THEN
    RAISE NOTICE 'Tidak ada lot proses di dryer — tidak ada yang digabung.';
    RETURN;
  END IF;

  FOR extra IN
    SELECT id FROM drying_lots WHERE status = 'proses' AND id <> keep_id
  LOOP
    -- Pindahkan batch (hindari duplikat pasangan lot+batch).
    UPDATE drying_lot_batches SET drying_lot_id = keep_id
      WHERE drying_lot_id = extra.id
        AND purchase_batch_id NOT IN (
          SELECT purchase_batch_id FROM drying_lot_batches WHERE drying_lot_id = keep_id
        );
    DELETE FROM drying_lot_batches WHERE drying_lot_id = extra.id;  -- sisa duplikat
    -- Pindahkan log terkait.
    UPDATE drying_moisture_logs SET drying_lot_id = keep_id WHERE drying_lot_id = extra.id;
    UPDATE drying_cooling_logs  SET drying_lot_id = keep_id WHERE drying_lot_id = extra.id;
    UPDATE silo_moving_logs     SET drying_lot_id = keep_id WHERE drying_lot_id = extra.id;
    -- Hapus lot ekstra.
    DELETE FROM drying_lots WHERE id = extra.id;
    RAISE NOTICE 'Lot id % digabung ke id %', extra.id, keep_id;
  END LOOP;
END $$;

-- Cek hasil: harus tinggal 1 lot 'proses'.
SELECT dl.id, dl.kode_lot, dl.status,
       (SELECT count(*) FROM drying_lot_batches x WHERE x.drying_lot_id = dl.id) AS n_batch
FROM drying_lots dl WHERE dl.status = 'proses' ORDER BY dl.id;
