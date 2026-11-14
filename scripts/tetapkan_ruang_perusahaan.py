"""Pratinjau/penetapan ruang data. Tidak mengubah transaksi, kredensial, atau saldo."""
import argparse,asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.config import settings
from hmu_identitas.ruang_data import RuangData
from app.services.ruang_perusahaan import pratinjau,terapkan


async def main(args):
    # Engine administratif tersendiri: identitas belum ada pada penetapan pertama.
    engine=create_async_engine(settings.database_url)
    @event.listens_for(engine.sync_engine,'before_cursor_execute')
    def pagar(conn,cursor,statement,parameters,context,executemany):
        import re
        awal=re.match(r'\s*([A-Za-z]+)',statement)
        if awal and awal[1].upper()=='SELECT':
            return
        m=re.match(r'\s*INSERT INTO\s+([a-z_]+)',statement,re.I)
        if not m or m[1] not in {'setelan_pabrik','activity_logs'}:
            raise RuntimeError('Penetapan hanya boleh membaca dan menambah metadata/audit.')
    try:
        async with async_sessionmaker(engine,expire_on_commit=False)() as db:
            ruang=RuangData(args.company_id,args.ruang_id,args.sesi_lama_sampai)
            plan=await pratinjau(db,ruang)
            if args.terapkan:
                plan=await terapkan(db,ruang,bukti=args.bukti,nama_persis=args.nama_persis,alasan=args.alasan)
                await db.commit()
            print(json.dumps(plan,ensure_ascii=False))
    finally:
        await engine.dispose()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--company-id',type=int,required=True);p.add_argument('--ruang-id',required=True)
    p.add_argument('--sesi-lama-sampai',type=int,default=0);p.add_argument('--terapkan',action='store_true')
    p.add_argument('--bukti',default='');p.add_argument('--nama-persis',default='');p.add_argument('--alasan',default='')
    asyncio.run(main(p.parse_args()))
