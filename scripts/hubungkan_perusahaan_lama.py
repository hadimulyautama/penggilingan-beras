"""Perintah satu kali; selalu periksa dahulu, terapkan hanya snapshot yang disetujui."""
import argparse,asyncio,json,sys,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal,engine
from app.services import organisasi_warisan as svc
from sqlalchemy import event

TABEL_METADATA={'hmu_companies','hmu_factory_sites','hmu_warehouse_sites','hmu_company_memberships','hmu_membership_sites','setelan_pabrik','activity_logs'}


@event.listens_for(engine.sync_engine,'before_cursor_execute')
def hanya_metadata(conn,cursor,statement,parameters,context,executemany):
    sql=statement.strip()
    match=re.match(r'(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"?([a-z_]+)',sql,re.I)
    if match and match[1] not in TABEL_METADATA:raise RuntimeError('Penetapan dilarang menulis tabel selain metadata organisasi.')
    awal=re.match(r'([A-Za-z]+)',sql)
    if not awal or awal[1].upper() not in {'SELECT','INSERT','UPDATE','DELETE'}:raise RuntimeError('Penetapan hanya menjalankan pembacaan dan penulisan metadata yang diizinkan.')


async def main(args):
    async with SessionLocal() as db:
        plan=await svc.pratinjau(db,kode=args.kode,lokasi_nama=args.lokasi,warehouse_ids=args.gudang)
        if args.terapkan:
            if not args.bukti or not args.alasan or not args.nama_persis:raise ValueError('Terapkan memerlukan bukti, alasan, dan nama identitas persis.')
            if not plan.get('sudah') and plan['nama']!=args.nama_persis:raise ValueError('Identitas lama berbeda; penetapan dihentikan.')
            cid=await svc.terapkan(db,kode=args.kode,lokasi_nama=args.lokasi,warehouse_ids=args.gudang,bukti=args.bukti,alasan=args.alasan,sistem=True)
            await db.commit();print(json.dumps(dict(company_id=cid,tersimpan=True)))
        else:
            # Tidak menampilkan daftar nama akun pada log administratif.
            if not plan.get('sudah'):plan={**plan,'pengguna':dict(jumlah=len(plan['pengguna']),admin=sum(u['peran']=='admin' for u in plan['pengguna']))}
            print(json.dumps(plan,ensure_ascii=False))
    await engine.dispose()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kode',required=True);p.add_argument('--lokasi',required=True)
    p.add_argument('--gudang',type=int,nargs='+',required=True);p.add_argument('--terapkan',action='store_true');p.add_argument('--bukti');p.add_argument('--alasan');p.add_argument('--nama-persis')
    asyncio.run(main(p.parse_args()))
