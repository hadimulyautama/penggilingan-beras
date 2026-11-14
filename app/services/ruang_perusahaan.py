"""Penetapan identitas koneksi, hanya metadata dan audit, sebelum aktivasi server."""
import hashlib
import json
from sqlalchemy import text
from hmu_identitas.ruang_data import KUNCI, RuangData


async def pratinjau(db, ruang: RuangData):
    company = (await db.execute(text('SELECT id,nama FROM hmu_companies WHERE id=:id'), {'id':ruang.company_id})).mappings().one_or_none()
    if not company:
        raise ValueError('Perusahaan belum terdaftar pada ruang data ini.')
    bindings = (await db.execute(text('SELECT w.id,p.company_id,p.lokasi_pabrik_id FROM warehouses w LEFT JOIN hmu_warehouse_sites p ON p.warehouse_id=w.id ORDER BY w.id'))).mappings().all()
    if any(r['company_id'] != ruang.company_id for r in bindings):
        raise ValueError('Semua gudang harus sudah ditetapkan ke perusahaan ruang ini.')
    old = await db.scalar(text('SELECT nilai FROM setelan_pabrik WHERE kunci=:k'), {'k':KUNCI})
    if old:
        ruang.cocokkan(old)
    legacy = await db.scalar(text("SELECT nilai FROM setelan_pabrik WHERE kunci='organisasi_perusahaan_lama'"))
    if legacy and json.loads(legacy)['company_id'] != ruang.company_id:
        raise ValueError('Data perusahaan lama tidak boleh diikat ke perusahaan lain.')
    if ruang.sesi_lama_sampai and not legacy:
        raise ValueError('Pengecualian sesi lama hanya untuk ruang perusahaan warisan yang sudah ditetapkan.')
    if not legacy and not old:
        # Penyediaan baru dimulai pada database tersendiri yang belum memiliki
        # transaksi atau akun. Tak ada operasi salin/migrasi data perusahaan lain.
        tables = list(await db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")))
        metadata = {'hmu_companies','hmu_factory_sites','hmu_warehouse_sites','setelan_pabrik'}
        for table in tables:
            if table in metadata or table.startswith('alembic_version'):
                continue
            # Nama berasal dari katalog dan dikutip oleh dialect, bukan input.
            name = db.bind.dialect.identifier_preparer.quote(table)
            if await db.scalar(text('SELECT EXISTS(SELECT 1 FROM '+name+' LIMIT 1)')):
                raise ValueError('Ruang baru harus disediakan pada database kosong sebelum akun/master/transaksi diisi.')
        if not await db.scalar(text("SELECT nilai FROM setelan_pabrik WHERE kunci='identitas_perusahaan'")):
            raise ValueError('Identitas dokumen perusahaan baru harus disiapkan terlebih dahulu.')
    plan = dict(company_id=company['id'],nama=company['nama'],ruang_id=ruang.ruang_id,
                sesi_lama_sampai=ruang.sesi_lama_sampai,gudang=[dict(r) for r in bindings],sudah=bool(old))
    plan['bukti'] = hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    return plan


async def terapkan(db,ruang,*,bukti,nama_persis,alasan):
    if db.new or db.dirty or db.deleted:
        raise ValueError('Penetapan harus memakai transaksi metadata tersendiri.')
    await db.execute(text('SELECT pg_advisory_xact_lock(18900132)'))
    plan = await pratinjau(db,ruang)
    if plan['sudah']:
        return plan
    if plan['bukti'] != bukti or plan['nama'] != nama_persis or len(alasan.strip()) < 10:
        raise ValueError('Pratinjau, nama perusahaan atau alasan tidak cocok.')
    nilai = json.dumps(dict(ruang.klaim(),sesi_lama_sampai=ruang.sesi_lama_sampai),sort_keys=True)
    await db.execute(text('INSERT INTO setelan_pabrik(kunci,nilai) VALUES (:k,:v)'), {'k':KUNCI,'v':nilai})
    await db.execute(text("""INSERT INTO activity_logs(table_name,record_id,action,field_name,new_value,alasan_perubahan,aksi)
        VALUES ('hmu_companies',:cid,'INSERT',:k,:v,:alasan,'penetapan_ruang_perusahaan')"""),
        {'cid':ruang.company_id,'k':KUNCI,'v':nilai,'alasan':alasan})
    return plan
