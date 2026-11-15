"""Peta akses dan pusat gangguan baca-saja; tidak mengubah sesi atau transaksi."""
import json
from datetime import timedelta
from sqlalchemy import select,func,or_,and_,text
from hmu_core import User,Perusahaan,KeanggotaanPerusahaan as M,LokasiPabrik,Warehouse,PenempatanGudang as W,ProdukAplikasiPerusahaan as CP,IntegrasiProdukPerusahaan as CI
from hmu_identitas.model import Akun
from hmu_identitas import peran as P,pintu
from hmu_identitas.produk import KATALOG,KODE,INTEGRASI,hak_pengguna,ProdukDitolak
from hmu_identitas.organisasi import konteks_kerja,OrganisasiTidakDiizinkan
from hmu_identitas.ruang_data import RuangData
from hmu_identitas.monitoring import KejadianPemakaian as E,SumberMonitoring as S
from app.services import console_monitoring as mon

KATEGORI=('server','browser','login','akses')

def id_sah(value):return type(value) is int and 0<value<=2147483647

def periksa(db,cid,produk,halaman=1):
    if db.new or db.dirty or db.deleted:raise ValueError('Pemeriksaan memerlukan transaksi baca tersendiri.')
    if cid is not None and not id_sah(cid):raise ValueError('Perusahaan tidak valid.')
    if produk not in ('',*KODE) or type(halaman) is not int or not 1<=halaman<=100000:raise ValueError('Produk atau halaman tidak valid.')

async def scope(db,cid=None,*,lokal=False):
    space=RuangData.lingkungan()
    if lokal and cid is None:cid=space.company_id if space else None
    chosen=await db.get(Perusahaan,cid,populate_existing=True) if cid else None
    if cid and not chosen:raise LookupError('Perusahaan tidak ditemukan.')
    options=list(await db.scalars(select(Perusahaan).order_by(Perusahaan.nama,Perusahaan.id).limit(20)))
    if chosen and all(c.id!=chosen.id for c in options):options.append(chosen)
    return dict(company_id=cid,nama=chosen.nama if chosen else '',aktif=chosen.aktif if chosen else None,tersedia=bool(chosen and space and cid==space.company_id),
        perusahaan=[dict(id=c.id,nama=c.nama) for c in options])

async def cari_pengguna(db,*,company_id=None,produk='',cari='',halaman=1):
    periksa(db,company_id,produk,halaman)
    if not isinstance(cari,str) or len(cari)>100:raise ValueError('Pencarian pengguna tidak valid.')
    with db.no_autoflush:
        ctx=await scope(db,company_id)
        q=select(User.id,User.nama,Akun.username).outerjoin(Akun,Akun.user_id==User.id)
        if company_id:q=q.where(mon.batas_identitas(company_id))
        cari=cari.strip()
        if cari:
            term='%'+cari.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            q=q.where(or_(User.nama.ilike(term,escape='\\'),Akun.username.ilike(term,escape='\\'),User.id==int(cari) if cari.isdecimal() and len(cari)<=10 and id_sah(int(cari)) else False))
        count=await db.scalar(select(func.count()).select_from(q.subquery()));pages=max(1,(count+19)//20);page=min(halaman,pages)
        rows=(await db.execute(q.order_by(func.lower(User.nama),User.id).offset((page-1)*20).limit(20))).all()
        return dict(cakupan=ctx,jenis='staf',akun_id=None,produk=produk,user_id=None,diperbarui=mon.sekarang().isoformat(),pengguna=[dict(user_id=i,nama=n,username=u or '') for i,n,u in rows],total=count,halaman=page,halaman_total=pages)

async def peta_akses(db,*,user_id,company_id=None,produk='',halaman=1):
    periksa(db,company_id,produk,halaman)
    if not id_sah(user_id):raise ValueError('Pengguna tidak valid.')
    with db.no_autoflush:
        ctx=await scope(db,company_id);user=await db.get(User,user_id,populate_existing=True)
        if not user:raise LookupError('Pengguna tidak ditemukan.')
        account=await db.scalar(select(Akun).where(Akun.user_id==user_id).execution_options(populate_existing=True))
        has_member=bool(await db.scalar(select(M.id).where(M.user_id==user_id).limit(1)))
        q=select(Perusahaan)
        if company_id:q=q.where(Perusahaan.id==company_id)
        elif not P.super_saja(user.role):
            q=q.where(or_(Perusahaan.id.in_(select(M.company_id).where(M.user_id==user_id)),
                Perusahaan.id.in_(select(CP.company_id).where(CP.warisan.is_(True))) if not has_member else False))
        count=await db.scalar(select(func.count()).select_from(q.subquery()));pages=max(1,(count+4)//5);page=min(halaman,pages)
        companies=list(await db.scalars(q.order_by(Perusahaan.nama,Perusahaan.id).offset((page-1)*5).limit(5)))
        rows=[];space=RuangData.lingkungan()
        for co in companies:
            connected=bool(space and space.company_id==co.id)
            member=await db.scalar(select(M).where(M.company_id==co.id,M.user_id==user_id).execution_options(populate_existing=True))
            products=[]
            product_rows={p.produk:p for p in await db.scalars(select(CP).where(CP.company_id==co.id))}
            tf_ready=connected and await mon.timbangan_siap(db)
            for definition in KATALOG:
                if produk and definition.kode!=produk:continue
                reason='';reason_code='';role='';source='';allowed=False
                try:
                    grant=await hak_pengguna(db,company_id=co.id,produk=definition.kode,user_id=user_id)
                    role,source=grant.peran,grant.sumber
                    reason=pintu.sebab_tolak(role,pintu.PRODUKSI if definition.kode=='padiflow' else pintu.TIMBANGAN) or '';reason_code='peran' if reason else ''
                    if not account or not account.aktif:reason='Akun masuk tidak aktif atau belum dibuat.';reason_code='akun'
                    elif account.harus_ganti_sandi:reason='Pengguna wajib mengganti sandi sebelum melanjutkan.';reason_code='sandi'
                    if not reason and tf_ready and definition.kode=='teraflow':
                        if await mon.profil_timbang_bersama_nonaktif(db,account.id):reason='Profil pos timbang dinonaktifkan.';reason_code='profil'
                    allowed=not reason
                except ProdukDitolak as e:
                    reason=str(e);row=product_rows.get(definition.kode)
                    reason_code='produk' if not co.aktif or not row or not row.aktif else 'user' if (user.status or '').lower()!='aktif' else 'anggota' if member and not member.aktif else 'izin'
                products.append(dict(kode=definition.kode,nama=definition.nama,izin_sesuai=allowed,peran=role,sumber=source,sebab=reason,sebab_kode=reason_code,
                    operasional='diizinkan' if allowed and connected and (definition.kode!='teraflow' or tf_ready) else 'belum_terhubung' if allowed else 'ditolak',
                    pintu=[dict(nama=pintu.NAMA_APLIKASI[g],boleh=allowed and pintu.boleh_masuk(role,g)) for g in ((pintu.PRODUKSI,pintu.GUDANG2,pintu.MEJA) if definition.kode=='padiflow' else (pintu.TIMBANGAN,))]))
            warehouses=[];more=False
            if connected and produk!='teraflow':
                wq=select(Warehouse,LokasiPabrik).join(W,W.warehouse_id==Warehouse.id).join(LokasiPabrik,and_(LokasiPabrik.id==W.lokasi_pabrik_id,LokasiPabrik.company_id==W.company_id)).where(W.company_id==co.id).order_by(Warehouse.nama_gudang,Warehouse.id)
                found=(await db.execute(wq.limit(21))).all();more=len(found)>20
                pf=next((p for p in products if p['kode']=='padiflow'),None)
                for wh,site in found[:20]:
                    assigned=False
                    try:await konteks_kerja(db,user_id=user_id,company_id=co.id,lokasi_pabrik_id=site.id,warehouse_id=wh.id);assigned=True
                    except OrganisasiTidakDiizinkan:pass
                    warehouses.append(dict(id=wh.id,nama=wh.nama_gudang,lokasi=site.nama,lokasi_aktif=site.aktif,aktif=wh.aktif,
                        kerja=bool(pf and pf['izin_sesuai'] and wh.aktif and P.boleh_ganti_gudang(pf['peran'])),penetapan=assigned))
            rows.append(dict(company_id=co.id,nama=co.nama,aktif=co.aktif,terhubung=connected,keanggotaan=member.peran if member else '',anggota_aktif=bool(member and member.aktif),produk=products,gudang=warehouses,gudang_lebih=more))
        return dict(cakupan=ctx,jenis='staf',akun_id=None,produk=produk,user_id=user_id,diperbarui=mon.sekarang().isoformat(),pengguna=dict(user_id=user.id,nama=user.nama,username=account.username if account else '',akun_id=account.id if account else None,aktif=bool(account and account.aktif),wajib_sandi=bool(account and account.harus_ganti_sandi)),perusahaan=rows,total=count,halaman=page,halaman_total=pages)

def kondisi():
    return dict(server=and_(E.jenis=='respons_web',E.kode.in_([str(n) for n in range(500,600)])),browser=E.jenis=='galat_browser',login=and_(E.jenis=='login',E.kode!='berhasil'),akses=and_(E.jenis=='respons_web',E.kode.in_(['401','403'])))

async def gangguan(db,*,company_id=None,produk='',jam=24,kategori='',halaman=1):
    periksa(db,company_id,produk,halaman)
    if type(jam) is not int or jam not in (1,24,168) or kategori not in ('',*KATEGORI):raise ValueError('Periode atau kategori gangguan tidak valid.')
    with db.no_autoflush:
        ctx=await scope(db,company_id,lokal=True);now=mon.sekarang();start=now-timedelta(hours=jam)
        result=dict(cakupan=ctx,produk=produk,user_id=None,jam=jam,kategori=kategori,diperbarui=now.isoformat(),layanan=[],kejadian=[],jumlah=None,total=None,halaman=1,halaman_total=1,integrasi=dict(status='belum_terhubung',peringatan=None))
        if not ctx['tersedia']:return result
        cid=ctx['company_id'];codes={p.produk for p in await db.scalars(select(CP).where(CP.company_id==cid,CP.aktif.is_(True)))}
        if not ctx.get('aktif'):codes=set()
        selected=[d for d in KATALOG if not produk or d.kode==produk]
        apps=[a for d in selected if d.kode in codes for a in d.aplikasi]
        sources={s.aplikasi:s for s in await db.scalars(select(S).where(S.company_id==cid,S.aplikasi.in_(apps)))}
        for definition in selected:
            active=definition.kode in codes
            result['layanan'].append(dict(kode=definition.kode,nama=definition.nama,aktif=active,pelaporan=[dict(aplikasi=a,status='segar' if a in sources and sources[a].terakhir<=now and sources[a].terakhir>=now-timedelta(seconds=120) else 'terlambat' if a in sources else 'belum_terpantau',terakhir=sources[a].terakhir.isoformat() if a in sources else None,versi=sources[a].versi if a in sources else '') for a in definition.aplikasi] if active else []))
        base=[E.company_id==cid,E.aplikasi.in_(apps),E.waktu>=start,E.waktu<=now];rules=kondisi()
        result['jumlah']={k:await db.scalar(select(func.count()).select_from(E).where(*base,cond)) for k,cond in rules.items()}
        # Kategori saling lepas: login merupakan kejadian tersendiri, akses adalah respons web.
        predicate=rules[kategori] if kategori else or_(*rules.values())
        where=[*base,predicate];count=await db.scalar(select(func.count()).select_from(E).where(*where));pages=max(1,(count+29)//30);page=min(halaman,pages)
        events=list(await db.scalars(select(E).where(*where).order_by(E.waktu.desc(),E.id.desc()).offset((page-1)*30).limit(30)))
        identities=await mon.sumber_akun(db,cid)
        pairs=[and_(identities.c.jenis==e.jenis_akun,identities.c.id==e.akun_id) for e in events if e.akun_id>0]
        names={(r['jenis'],r['id']):dict(r) for r in (await db.execute(select(identities).where(or_(*pairs)))).mappings()} if pairs else {}
        for event in events:
            person=names.get((event.jenis_akun,event.akun_id));kind='login' if event.jenis=='login' else 'browser' if event.jenis=='galat_browser' else 'akses' if event.kode in ('401','403') else 'server'
            result['kejadian'].append(dict(id=event.id,company_id=event.company_id,aplikasi=event.aplikasi,kategori=kind,kode=event.kode,layar=event.layar,waktu=event.waktu.isoformat(),nama=person['nama'] if person else '',jenis=event.jenis_akun if person else '',akun_id=event.akun_id if person else None,user_id=person['user_id'] if person else None))
        result.update(total=count,halaman=page,halaman_total=pages)
        integration=await db.get(CI,(cid,INTEGRASI),populate_existing=True)
        if set(KODE)<=codes and integration and integration.aktif:
            result['integrasi']=dict(status='aktif',peringatan=None)
            cols=set(await db.scalars(text("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='timbangan_kiriman'")))
            if {'created_at','jawaban','kunci'}<=cols:
                receipts=(await db.execute(text('SELECT jawaban FROM timbangan_kiriman WHERE created_at>=:start AND created_at<=:now ORDER BY created_at DESC,kunci LIMIT 101'),dict(start=start,now=now))).scalars().all()
                warning=invalid=0
                for raw in receipts[:100]:
                    try:
                        value=json.loads(raw) if raw else {}
                        if not isinstance(value,dict):raise ValueError()
                        warning+=int(value.get('peringatan') is True)
                    except (ValueError,TypeError):invalid+=1
                result['integrasi'].update(peringatan=warning,tanda_terima=min(len(receipts),100),lebih=len(receipts)>100,tidak_terbaca=invalid)
        else:result['integrasi']=dict(status='tidak_digunakan',peringatan=None)
        return result


async def peta_akun_lokal(db,*,jenis,akun_id=None,company_id=None,produk='',cari='',halaman=1):
    periksa(db,company_id,produk,halaman)
    if jenis not in ('pelanggan','timbangan_lama') or (produk and produk!=('padiflow' if jenis=='pelanggan' else 'teraflow')):raise ValueError('Jenis akun dan produk tidak cocok.')
    with db.no_autoflush:
        ctx=await scope(db,company_id,lokal=True)
        if akun_id is None:
            found=await mon.daftar_akun(db,company_id=ctx['company_id'],jenis=jenis,cari=cari,halaman=halaman,limit=20)
            return dict(cakupan=ctx,jenis=jenis,user_id=None,akun_id=None,produk=produk,diperbarui=mon.sekarang().isoformat(),pengguna=[dict(user_id=None,akun_id=a['id'],jenis=jenis,nama=a['nama'],username=a['username']) for a in found['pengguna']],total=found['total'] if ctx['tersedia'] else None,halaman=found['halaman'],halaman_total=found['halaman_total'])
        if not id_sah(akun_id):raise ValueError('Akun tidak valid.')
        mon.pastikan_lokal(ctx['company_id'])
        from app.services.console_bantuan import diagnosis
        info=await diagnosis(db,cid=ctx['company_id'],jenis=jenis,aid=akun_id);a=info['akun'];app=info['aplikasi'][0]
        code='padiflow' if jenis=='pelanggan' else 'teraflow'
        if a['wajib_ganti']:app=dict(app,boleh=False,sebab='wajib_ganti_sandi',pesan='Pengguna wajib mengganti sandi sebelum melanjutkan.')
        return dict(cakupan=ctx,jenis=jenis,user_id=None,akun_id=akun_id,produk=produk,diperbarui=mon.sekarang().isoformat(),pengguna=dict(user_id=a['user_id'],akun_id=a['id'],nama=a['nama'],username=a['username'],aktif=a['aktif'],wajib_sandi=a['wajib_ganti']),total=1,halaman=1,halaman_total=1,
            perusahaan=[dict(company_id=ctx['company_id'],nama=ctx['nama'],terhubung=True,keanggotaan='',anggota_aktif=False,gudang=[],gudang_lebih=False,
            produk=[dict(kode=code,nama=next(d.nama for d in KATALOG if d.kode==code),izin_sesuai=app['boleh'],operasional='diizinkan' if app['boleh'] else 'ditolak',peran=app.get('peran_produk',a['peran']),sumber='akun_lokal',sebab=app.get('pesan') or ('' if app['boleh'] else app['sebab']),sebab_kode={'wajib_ganti_sandi':'sandi','akun_nonaktif':'akun','perusahaan_nonaktif':'produk','produk_nonaktif':'produk','akses_produk':'izin','peran':'peran'}.get(app['sebab'],'izin'),pintu=[dict(nama='Portal pelanggan' if jenis=='pelanggan' else 'Pos Timbang',boleh=app['boleh'])])])])
