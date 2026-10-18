"""Ringkasan pemeriksaan operator; token mencakup hasil dan setiap siklus silo."""
import hashlib
import json
from sqlalchemy import select
from app.models import (MillingProcess, MillingProcessSource, SiloStorage, Silo,
                        PolishingProcess, PolishingSiloUsage)


async def ringkasan_selesai(db, *, jenis: str, kode: str, berat_akhir=None):
    if jenis == 'giling':
        from app.penggilingan.gudang1.services.milling import _latest_progress
        proc = await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses == kode))
        if proc is None or proc.status != 'proses':
            raise ValueError('Proses giling sudah selesai atau tidak ditemukan.')
        rows = (await db.execute(select(MillingProcessSource, Silo.nama_silo)
            .join(SiloStorage, SiloStorage.id == MillingProcessSource.silo_storage_id)
            .join(Silo, Silo.id == SiloStorage.silo_id)
            .where(MillingProcessSource.milling_process_id == proc.id)
            .order_by(MillingProcessSource.id))).all()
        hasil = await _latest_progress(db, proc.id)
        final = berat_akhir if berat_akhir is not None else hasil
        if final is None or float(final) <= 0:
            raise ValueError('Isi hasil akhir PK sebelum memeriksa penyelesaian.')
        sumber = [[r.id, nama, str(r.berat_kg), str(r.berat_akhir_kg)] for r,nama in rows]
        aktif = sorted({nama for r,nama in rows if r.berat_akhir_kg is None})
        if not rows and proc.silo_id:
            silo = await db.get(Silo, proc.silo_id)
            aktif = [silo.nama_silo] if silo else []
        teks = (f'{kode}\nSilo yang masih terikat: {", ".join(aktif) or "tidak ada (semua sudah dibebaskan)"}.\n'
                f'Hasil akhir PK: {float(final):g} kg.\n'
                'Menyelesaikan giling menutup proses dan menganggap seluruh bahan pada silo yang masih terikat habis dipakai. '
                'Jika ada sisa, kembali dan gunakan Bebaskan silo untuk mencatatnya. '
                'Bebaskan silo mempertahankan proses berjalan. Riwayat silo yang sudah dibebaskan tetap tersimpan.')
        keadaan = [jenis, proc.id, proc.status, proc.jasa_id, str(proc.berat_gabah_masuk_kg), hasil, float(final), sumber]
    elif jenis == 'sosoh':
        from app.services.stok import output_sosoh
        proc = await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses == kode))
        if proc is None or proc.status != 'proses':
            raise ValueError('Proses penyosohan sudah selesai atau tidak ditemukan.')
        rows = (await db.execute(select(PolishingSiloUsage, Silo.nama_silo)
            .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
            .where(PolishingSiloUsage.polishing_process_id == proc.id)
            .order_by(PolishingSiloUsage.id))).all()
        if any(r.berat_akhir_kg is None for r,_ in rows):
            raise ValueError('Bebaskan semua silo dan catat sisanya terlebih dahulu. Penyosohan tetap berjalan.')
        hasil = await output_sosoh(db, proc.id)
        if not hasil:
            raise ValueError('Catat hasil penyosohan sebelum menyelesaikan proses.')
        sumber = [[r.id, nama, str(r.berat_awal_kg), str(r.berat_masuk_kg), str(r.berat_akhir_kg)] for r,nama in rows]
        teks = (f'{kode}\nSemua silo sudah dibebaskan; penyosohan masih berjalan.\nHasil tercatat: '
                + '; '.join(f'{j} {kg:g} kg' for j,kg in sorted(hasil.items()))
                + '.\nKonfirmasikan hanya jika seluruh bahan sudah selesai melewati mesin dan semua hasil sudah dicatat. '
                'Setelah selesai, pencatatan hasil proses ini ditutup. Packing hasil yang tersedia tetap bisa dilakukan.')
        keadaan = [jenis, proc.id, proc.status, proc.jasa_id, hasil, sumber]
    else:
        raise ValueError('Jenis proses tidak dikenal.')
    dasar = hashlib.sha256(json.dumps(keadaan,sort_keys=True).encode()).hexdigest()
    return {'dasar':dasar, 'teks':teks}
