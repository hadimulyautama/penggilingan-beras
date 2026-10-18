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
            .order_by(MillingProcessSource.id).execution_options(populate_existing=True))).all()
        hasil = await _latest_progress(db, proc.id)
        final = berat_akhir if berat_akhir is not None else hasil
        if final is None or float(final) <= 0:
            raise ValueError('Isi hasil akhir PK sebelum memeriksa penyelesaian.')
        sumber = [[r.id, nama, str(r.berat_kg), str(r.berat_akhir_kg)] for r,nama in rows]
        aktif = sorted({nama for r,nama in rows if r.berat_akhir_kg is None})
        if not rows or aktif:
            belum = ", ".join(aktif) or "sumber proses lama belum terverifikasi"
            raise ValueError(f'Periksa dan catat sisa setiap silo melalui Bebaskan silo terlebih dahulu: {belum}. Isi 0 hanya jika benar-benar kosong. Proses belum diselesaikan.')
        if proc.bobot_masuk_final and all(r.berat_terpakai_kg is not None for r,_ in rows):
            if float(final) >= sum(float(r.berat_terpakai_kg) for r,_ in rows):
                raise ValueError('Hasil PK harus lebih ringan dari bahan yang benar-benar terpakai setelah sisa silo dikurangkan.')
        rincian = '; '.join(f'{nama}: sisa {float(r.berat_akhir_kg):g} kg' for r,nama in rows)
        teks = (f'{kode}\nPemeriksaan silo: {rincian}.\n'
                f'Hasil akhir PK: {float(final):g} kg.\n'
                'Konfirmasikan hanya jika seluruh proses di mesin benar-benar selesai. '
                'Penyelesaian tidak mengosongkan silo. Sisa yang tercatat tetap tersedia di silo; '
                'hanya silo dengan sisa 0 kg yang dinyatakan kosong. Riwayat pemakaian tetap tersimpan.')
        keadaan = [jenis, proc.id, proc.status, proc.jasa_id, str(proc.berat_gabah_masuk_kg), hasil, float(final), sumber]
    elif jenis == 'sosoh':
        from app.services.stok import output_sosoh
        proc = await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses == kode))
        if proc is None or proc.status != 'proses':
            raise ValueError('Proses penyosohan sudah selesai atau tidak ditemukan.')
        rows = (await db.execute(select(PolishingSiloUsage, Silo.nama_silo)
            .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
            .where(PolishingSiloUsage.polishing_process_id == proc.id)
            .order_by(PolishingSiloUsage.id).execution_options(populate_existing=True))).all()
        if not rows or any(r.berat_akhir_kg is None for r,_ in rows):
            raise ValueError('Bebaskan semua silo dan catat sisanya terlebih dahulu. Penyosohan tetap berjalan.')
        hasil = await output_sosoh(db, proc.id)
        if not hasil:
            raise ValueError('Catat hasil penyosohan sebelum menyelesaikan proses.')
        if sum(hasil.values()) > sum(float(r.berat_terpakai_kg or 0) for r,_ in rows) + 0.001:
            raise ValueError('Total hasil melebihi bahan yang benar-benar terpakai setelah sisa silo dikurangkan.')
        sumber = [[r.id, nama, str(r.berat_awal_kg), str(r.berat_masuk_kg), str(r.berat_akhir_kg)] for r,nama in rows]
        teks = (f'{kode}\nSemua silo sudah diperiksa; penyosohan masih berjalan.\n'
                + 'Pemeriksaan silo: ' + '; '.join(f'{nama}: sisa {float(r.berat_akhir_kg):g} kg' for r,nama in rows)
                + '. Sisa tetap berada di silo; penyelesaian tidak mengosongkannya.\nHasil tercatat: '
                + '; '.join(f'{j} {kg:g} kg' for j,kg in sorted(hasil.items()))
                + '.\nKonfirmasikan hanya jika seluruh bahan sudah selesai melewati mesin dan semua hasil sudah dicatat. '
                'Setelah selesai, pencatatan hasil proses ini ditutup. Packing hasil yang tersedia tetap bisa dilakukan.')
        keadaan = [jenis, proc.id, proc.status, proc.jasa_id, hasil, sumber]
    else:
        raise ValueError('Jenis proses tidak dikenal.')
    dasar = hashlib.sha256(json.dumps(keadaan,sort_keys=True).encode()).hexdigest()
    return {'dasar':dasar, 'teks':teks}

async def ringkasan_bebaskan(db, *, jenis: str, kode: str, silo: str = '', sisa: float):
    """Pemeriksaan satu siklus silo, terikat pada identitas sumber dan bobotnya."""
    import math
    sisa = float(sisa)
    if not math.isfinite(sisa) or sisa < 0:
        raise ValueError('Isi sisa nol atau lebih. Isi 0 hanya jika silo benar-benar kosong.')
    if jenis == 'giling':
        proc = await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses == kode))
        rows = (await db.execute(select(MillingProcessSource, Silo.nama_silo)
            .join(SiloStorage, SiloStorage.id == MillingProcessSource.silo_storage_id)
            .join(Silo, Silo.id == SiloStorage.silo_id)
            .where(MillingProcessSource.milling_process_id == (proc.id if proc else -1),
                MillingProcessSource.berat_akhir_kg.is_(None)).order_by(MillingProcessSource.id)
            .execution_options(populate_existing=True))).all()
        rincian = [(r.id, nama, float(r.berat_kg) if r.berat_kg is not None else None) for r,nama in rows]
    elif jenis == 'sosoh':
        proc = await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses == kode))
        rows = (await db.execute(select(PolishingSiloUsage, Silo.nama_silo)
            .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
            .where(PolishingSiloUsage.polishing_process_id == (proc.id if proc else -1),
                PolishingSiloUsage.berat_akhir_kg.is_(None)).order_by(PolishingSiloUsage.id)
            .execution_options(populate_existing=True))).all()
        rincian = [(r.id, nama, float(r.berat_awal_kg or 0)+float(r.berat_masuk_kg or 0)) for r,nama in rows]
    else:
        raise ValueError('Jenis proses tidak dikenal.')
    if proc is None or proc.status != 'proses':
        raise ValueError('Proses sudah selesai atau tidak ditemukan.')
    nama = silo.upper().replace('SILO ', '').strip()
    pilihan = {n.replace('Silo ', '') for _,n,_ in rincian}
    if not nama and len(pilihan) == 1:
        nama = next(iter(pilihan))
    sumber = [r for r in rincian if r[1].replace('Silo ', '') == nama]
    if not sumber:
        raise ValueError('Silo tidak lagi terbuka untuk proses ini. Muat ulang dan periksa kembali.')
    tahu = all(kg is not None for _,_,kg in sumber)
    masuk = sum(kg or 0 for _,_,kg in sumber)
    if (tahu and sisa > masuk) or (not tahu and sisa != 0):
        raise ValueError('Sisa melebihi bahan tercatat atau bobot bahan belum diketahui. Periksa angkanya.')
    keadaan = [jenis, proc.id, nama, sumber, sisa]
    dasar = hashlib.sha256(json.dumps(keadaan,sort_keys=True).encode()).hexdigest()
    jumlah = f'{masuk:g} kg' if tahu else 'belum diketahui; menunggu timbang'
    akibat = 'Silo dinyatakan kosong dan dapat diisi ulang.' if sisa == 0 else 'Sisa tetap berada di silo. Status silo tetap terisi.'
    return {'dasar':dasar, 'teks':f'{kode} · Silo {nama}\nBahan masuk: {jumlah}.\nSisa yang diperiksa: {sisa:g} kg.\n{akibat}\nHanya ikatan silo yang dilepas; proses di mesin tetap berjalan.'}
