from pathlib import Path
from io import BytesIO
from uuid import uuid4
from datetime import timedelta
import json,hashlib
import pytest
from sqlalchemy import select
from bs4 import BeautifulSoup
from pypdf import PdfReader
from app.models import Silo,PkPurchaseBatch,PkGudang2Intake,User,Pelanggan,Jasa,PolishingProcess,PolishingOutputLog,PolishingSiloUsage,Peristiwa,ActivityLog,FinishedGoodsStock,ByproductStock
from app.models.portal import PortalAccount
from app.database import now_local
from app.services import jasa_pelanggan,pengemasan_otomatis as auto,koreksi_pengemasan_asal as koreksi
from app.services.koreksi_pengiriman import cap
from app.web.security import hash_sandi
from tests.pg.test_barang_keluar import gudang,_klien
from tests.pg.test_portal_pelanggan import client
pytestmark=pytest.mark.asyncio
OUT=Path('/Users/wahidnurhani/Developer/Hadi Mulya Systems/output/perbaikan-rekap-otomatis-20261104')
async def fingerprint(db):
 from app.services.koreksi_bahan_berjalan import raw
 d={m.__tablename__:[raw(x) for x in (await db.scalars(select(m).order_by(m.id))).all()] for m in (PolishingProcess,PolishingOutputLog,PolishingSiloUsage,Peristiwa,ActivityLog,FinishedGoodsStock,ByproductStock,Jasa,PkPurchaseBatch,PkGudang2Intake)}
 return hashlib.sha256(json.dumps(d,sort_keys=True,default=str).encode()).hexdigest()
@pytest.mark.parametrize('kind',['broken','bekatul','menir','reject'])
async def test_konsistensi(pg,gudang,kind):
 OUT=Path('/Users/wahidnurhani/Developer/Hadi Mulya Systems/output/perbaikan-rekap-otomatis-20261104')/kind
 OUT.mkdir(exist_ok=True)
 size=40 if kind=='bekatul' else 50
 async with pg() as db:
  owners=[Pelanggan(nama_pelanggan='Pemilik A Uji Pengemasan',kledo_contact_id=99101),Pelanggan(nama_pelanggan='RAHASIA Pemilik B',kledo_contact_id=99102)];db.add_all(owners);await db.flush()
  orders=[Jasa(kode='JAS-AUTO-A',pelanggan_id=owners[0].id,status='berjalan',hasil_ditahan=''),Jasa(kode='JAS-AUTO-B',pelanggan_id=owners[1].id,status='berjalan',hasil_ditahan='')];db.add_all(orders);await db.flush();procs=[];notes=[]
  for i in range(2):
   silo=Silo(nama_silo='Silo audit '+str(i),warehouse_id=(await db.get(Silo,gudang['silo'])).warehouse_id,status='kosong',jenis_isi='pk');db.add(silo);await db.flush()
   start=now_local()-timedelta(hours=1)
   batch=PkPurchaseBatch(kode_batch='PK-AUTO-'+str(i),jasa_id=orders[i].id,berat_total_kg=2000,tanggal_pembelian=start.date(),waktu_pembelian=start-timedelta(minutes=2),input_by=gudang['op'],status_batch='diterima',sumber_berat='manual');db.add(batch);await db.flush()
   db.add(PkGudang2Intake(sumber_tipe='beli_luar',pk_purchase_batch_id=batch.id,tujuan='silo',silo_id=silo.id,berat_kg=2000,bobot_final=True,tanggal_masuk=start.date(),waktu_masuk=start-timedelta(minutes=1),input_by=gudang['op'],jasa_id=orders[i].id))
   pr=PolishingProcess(kode_proses='POL-AUTO-'+('A' if i==0 else 'RAHASIA-B'),status='selesai',jasa_id=orders[i].id,created_by=gudang['op'],waktu_mulai=start,waktu_selesai=now_local());db.add(pr);await db.flush();procs.append(pr.id)
   db.add(PolishingSiloUsage(polishing_process_id=pr.id,silo_id=silo.id,berat_awal_kg=2000,berat_masuk_kg=0,berat_akhir_kg=0,berat_terpakai_kg=2000))
   for kg in ([325,925] if i==0 else [777]):
    row=PolishingOutputLog(polishing_process_id=pr.id,jenis=kind,berat_kg=kg,waktu_update=now_local(),input_by=gudang['op']);db.add(row);await db.flush()
    if i==0:notes.append(row.id)
  accounts=[PortalAccount(username='auto-portal-'+str(i),pelanggan_id=x.id,password_hash=hash_sandi('Uji-Portal-2026!'),active=True,token_version=1) for i,x in enumerate(owners)];db.add_all(accounts);await db.commit();customer=owners[0].id;order=orders[0].id;pid=procs[0]
 results=[];findings=[]
 async with await _klien(pg,gudang['adm'],'audit-pembaca-auto') as staff,client(accounts[0]) as portal,client(accounts[1]) as portal_b:
  for stage,total,bags,bulk in [('awal',1250,25,0),('koreksi',1175,23,25),('batal',925,18,25),('dipakai',925,14,25)]:
   available=725 if stage=='dipakai' else total
   bags=int(available//size);bulk=available%size
   if stage=='dipakai':
    from app.services import barang_keluar as bk
    async with pg() as db:
     h=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),pelanggan_id=customer,baris=[bk.BarisPerintah(tipe='byproduct_curah',jenis=kind,jasa_id=order,berat_kg=200)])
     await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=h.rec.id)
   if stage not in ('awal','dipakai'):
    req=dict(catatan_id=notes[0],aksi='ubah' if stage=='koreksi' else 'batal',kg='250' if stage=='koreksi' else '',alasan='Uji konsistensi '+stage)
    async with pg() as db:
     u=await db.get(User,gudang['adm']);plan=await koreksi.rencana(db,pid,kind,u,req);await koreksi.simpan(db,pid,kind,u,req,dasar=cap(plan),kunci=uuid4().hex);await db.commit()
   async with pg() as db:
    c=await auto.ringkasan(db,await db.get(PolishingProcess,pid),kind);j=await jasa_pelanggan.pelanggan(db,customer)
    assert (c['total_proses'],c['saldo_pemilik'],c['karung'],c['curah'])==(total,available,bags,bulk)
    assert j['samping_kg']==available
    from app.services.jasa import rekap_barang_jasa
    rekap=await rekap_barang_jasa(db,order)
    assert sum(r['kg'] for r in rekap['sisa'] if r['nama']==auto.stok.nama_produk(kind).capitalize())==available
    assert (await auto.ringkasan(db,await db.get(PolishingProcess,procs[1]),kind))['saldo_pemilik']==777
    before=await fingerprint(db)
   checks=[('stok',staff,f'/stok-produk-jasa/detail?jenis={kind}&pelanggan_id={customer}'),('jasa',staff,f'/jasa/pelanggan/{customer}?tab=stok'),('rekap',staff,f'/jasa/{order}/nota'),('portal-stok',portal,'/pelanggan/stok?tab=produk'),('portal-barang',portal,'/pelanggan/barang-saya'),('portal-detail',portal,f'/pelanggan/stok-produk-jasa/detail?jenis={kind}&pelanggan_id={customer}'),('portal-rekap',portal,f'/pelanggan/jasa/{order}/nota')]
   value=f'{available:,}'.replace(',','.')
   for name,c,url in checks:
    r=await c.get(url);assert r.status_code==200,(name,r.status_code,r.text[:400]);text=BeautifulSoup(r.text,'html.parser').get_text(' ',strip=True);(OUT/(stage+'-'+name+'.html')).write_text(r.text)
    
    if value not in text:findings.append(dict(tahap=stage,pembaca=name,total_diharapkan=total,keterangan='Total efektif tidak tercantum pada halaman'))
    assert 'RAHASIA' not in text
    if name in ('stok','portal-detail'):
     assert str(bags)+' karung' in text and f'{bulk} kg' in text
    if name=='jasa' and stage!='awal' and f'{available:,}'.replace(',','.')+' kg belum dikemas' in text:findings.append(dict(tahap=stage,pembaca='jasa-label-kemasan',keterangan='Seluruh saldo disebut belum dikemas; Stok merinci kemasan otomatis dan sisa curah.'))
   for name,c,url in [('proses',staff,f'/riwayat-sosoh/{pid}/laporan.pdf'),('rekap',staff,f'/jasa/{order}/nota.pdf'),('portal-proses',portal,f'/pelanggan/riwayat-sosoh/{pid}/laporan.pdf'),('portal-rekap',portal,f'/pelanggan/jasa/{order}/nota.pdf')]:
    r=await c.get(url);assert r.status_code==200,(name,r.status_code);assert r.content.startswith(b'%PDF');path=OUT/(stage+'-'+name+'.pdf');path.write_bytes(r.content);pdf=PdfReader(BytesIO(r.content));text='\n'.join(x.extract_text() or '' for x in pdf.pages);path.with_suffix('.txt').write_text(text)
    
    pdf_value=format(total if name in ('proses','portal-proses') else available,',').replace(',','.')
    if pdf_value not in text:findings.append(dict(tahap=stage,pembaca='pdf-'+name,total_diharapkan=total,keterangan='Total efektif tidak tercantum pada PDF'))
    assert 'RAHASIA' not in text
   for c,url in [(portal,f'/pelanggan/riwayat-sosoh/{procs[1]}/laporan.pdf'),(portal_b,f'/pelanggan/riwayat-sosoh/{pid}/laporan.pdf'),(portal_b,f'/pelanggan/jasa/{order}/nota.pdf')]:assert (await c.get(url)).status_code==404
   rb=await portal_b.get(f'/pelanggan/stok-produk-jasa/detail?jenis={kind}&pelanggan_id={customer}');assert rb.status_code in (200,404)
   if rb.status_code==200:assert 'Pemilik A Uji Pengemasan' not in rb.text
   async with pg() as db:assert await fingerprint(db)==before,'GET mengubah data operasional'
   results.append(dict(tahap=stage,total=total,saldo=available,karung=bags,curah=bulk,pembaca=11,read_only=True))
 assert not findings,findings
 (OUT/'hasil.json').write_text(json.dumps(dict(tahapan=results,ketidaksesuaian=findings),indent=2))
