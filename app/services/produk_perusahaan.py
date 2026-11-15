"""Writer metadata produk; transaksi bisnis/kredensial tidak disentuh."""
import json
from sqlalchemy import select,delete
from hmu_core import Perusahaan,User,KeanggotaanPerusahaan,ProdukAplikasiPerusahaan,AksesProdukAnggota,IntegrasiProdukPerusahaan
from hmu_identitas import peran as P
from hmu_identitas.produk import KATALOG,KODE,INTEGRASI,PERAN
from app.services import keanggotaan as anggota
from app.services.organisasi_master import OrganisasiError,teks
from app.services.activity_log import log_activity

async def rincian(db,*,ruang,company_id,user_id=None):
    with db.no_autoflush:
        _,own=await anggota.otorisasi(db,ruang,company_id)
        if own is not None:raise PermissionError('Aktivasi dan penetapan produk dikelola melalui Console Admin Sistem.')
        co=await db.get(Perusahaan,company_id)
        if not co:raise OrganisasiError('Perusahaan tidak tersedia.')
        rows={p.produk:p for p in await db.scalars(select(ProdukAplikasiPerusahaan).where(ProdukAplikasiPerusahaan.company_id==company_id).execution_options(populate_existing=True))}
        integration=await db.get(IntegrasiProdukPerusahaan,(company_id,INTEGRASI),populate_existing=True)
        from hmu_identitas.ruang_data import RuangData
        local=RuangData.lingkungan()
        data=dict(company_id=company_id,perusahaan=co.nama,company_aktif=co.aktif,ruang_lokal=bool(local and local.company_id==company_id),produk=[dict(kode=d.kode,nama=d.nama,aktif=bool(rows.get(d.kode) and rows[d.kode].aktif),warisan=bool(rows.get(d.kode) and rows[d.kode].warisan),ditetapkan=d.kode in rows) for d in KATALOG],integrasi=bool(integration and integration.aktif))
        if user_id is not None:
            if not anggota.id_sah(user_id):raise OrganisasiError('Pengguna tidak valid.')
            member=await db.scalar(select(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.company_id==company_id,KeanggotaanPerusahaan.user_id==user_id).execution_options(populate_existing=True))
            user=await db.get(User,user_id,populate_existing=True)
            if not member or not user:raise OrganisasiError('Pengguna bukan anggota perusahaan ini.')
            grants={g.produk:g for g in await db.scalars(select(AksesProdukAnggota).where(AksesProdukAnggota.company_id==company_id,AksesProdukAnggota.user_id==user_id).execution_options(populate_existing=True))}
            # Keanggotaan di perusahaan lain meniadakan fallback warisan,
            # termasuk bila keanggotaan itu nonaktif. Ini sama dengan gerbang
            # produk; pilihan Console dan bukti pratinjau harus mengikutinya.
            lintas=bool(await db.scalar(select(KeanggotaanPerusahaan.id).where(
                KeanggotaanPerusahaan.user_id==user_id,KeanggotaanPerusahaan.company_id!=company_id).limit(1)))
            data.update(user_id=user_id,nama=user.nama,platform=P.super_saja(user.role),peran_master=P.normal(user.role),
                pengguna_aktif=(user.status or '').lower()=='aktif',warisan_boleh=not lintas,
                keanggotaan=await anggota.snapshot(db,member),akses=[])
            for p in data['produk']:
                g=grants.get(p['kode']);mode=g.peran if g and g.aktif else 'nonaktif' if g else 'warisan' if p['warisan'] else 'nonaktif'
                data['akses'].append(dict(produk=p['kode'],mode=mode))
        data['bukti']=anggota.sidik(data)
        return data

async def _kunci(db,ruang,cid):
    if db.new or db.dirty or db.deleted:raise OrganisasiError('Perubahan produk harus memakai transaksi metadata tersendiri.')
    await db.scalar(select(Perusahaan).where(Perusahaan.id==cid).with_for_update().execution_options(populate_existing=True))
    _,own=await anggota.otorisasi(db,ruang,cid)
    if own is not None:raise PermissionError('Pengaturan produk hanya untuk Admin Sistem.')

async def simpan(db,*,ruang,company_id,produk,integrasi,bukti,alasan):
    alasan=teks(alasan,'Alasan perubahan',500,10)
    if type(integrasi) is not bool or not isinstance(produk,list) or len(produk)!=len(KODE) or any(not isinstance(p,dict) or set(p)!={'kode','aktif'} or p['kode'] not in KODE or type(p['aktif']) is not bool for p in produk) or {p['kode'] for p in produk}!=set(KODE):raise OrganisasiError('Daftar aktivasi produk tidak valid.')
    desired={p['kode']:p['aktif'] for p in produk}
    if integrasi and not all(desired.values()):raise OrganisasiError('Integrasi memerlukan PadiFlow dan TeraFlow aktif.')
    await _kunci(db,ruang,company_id);before=await rincian(db,ruang=ruang,company_id=company_id)
    if bukti!=before['bukti']:raise OrganisasiError('Pengaturan produk telah berubah. Tinjau ulang sebelum menyimpan.')
    same=all(p['aktif']==desired[p['kode']] and p['ditetapkan'] for p in before['produk']) and integrasi==before['integrasi']
    if same:return before
    for code,active in desired.items():
        row=await db.get(ProdukAplikasiPerusahaan,(company_id,code))
        if row is None:row=ProdukAplikasiPerusahaan(company_id=company_id,produk=code,warisan=False);db.add(row)
        row.aktif=active
    row=await db.get(IntegrasiProdukPerusahaan,(company_id,INTEGRASI))
    if row is None:row=IntegrasiProdukPerusahaan(company_id=company_id,kode=INTEGRASI);db.add(row)
    row.aktif=integrasi;await db.flush()
    after=await rincian(db,ruang=ruang,company_id=company_id)
    await log_activity(db,table_name='hmu_company_products',record_id=company_id,action='UPDATE',changed_by=ruang.user_id,field_name=f'company:{company_id}:produk',old_value=json.dumps(before,ensure_ascii=False),new_value=json.dumps(after,ensure_ascii=False),alasan=alasan,aksi='produk_perusahaan')
    return after

async def simpan_akses(db,*,ruang,company_id,user_id,akses,bukti,alasan):
    alasan=teks(alasan,'Alasan perubahan',500,10)
    if not anggota.id_sah(user_id):raise OrganisasiError('Pengguna tidak valid.')
    if not isinstance(akses,list) or len(akses)!=len(KODE) or any(not isinstance(a,dict) or set(a)!={'produk','mode'} or a['produk'] not in KODE or a['mode'] not in (*PERAN,'nonaktif','warisan') for a in akses) or {a['produk'] for a in akses}!=set(KODE):raise OrganisasiError('Hak akses produk tidak valid.')
    await _kunci(db,ruang,company_id)
    # Satu pengguna dapat diatur dari beberapa perusahaan sekaligus. Urutan
    # perusahaan -> pengguna -> anggota sama dengan writer keanggotaan,
    # sehingga fallback warisan tidak diputuskan dari penugasan yang separuh.
    await db.scalar(select(User).where(User.id==user_id).with_for_update().execution_options(populate_existing=True))
    before=await rincian(db,ruang=ruang,company_id=company_id,user_id=user_id)
    if before['platform']:raise OrganisasiError('Peran platform tidak dapat diubah melalui akses produk. Produk perusahaan tetap harus aktif.')
    if bukti!=before['bukti']:raise OrganisasiError('Keanggotaan atau akses produk telah berubah. Tinjau ulang sebelum menyimpan.')
    products={p['kode']:p for p in before['produk']}
    # Validasi seluruh rencana sebelum mengubah ORM. Penolakan produk kedua
    # tidak boleh meninggalkan perubahan produk pertama bagi pemanggil lain.
    for a in akses:
        p=products[a['produk']]
        if a['mode']=='warisan':
            if not p['warisan']:raise OrganisasiError('Akses warisan hanya tersedia untuk produk perusahaan lama yang ditetapkan saat migrasi.')
            if not before['warisan_boleh']:raise OrganisasiError('Pengguna beberapa perusahaan memerlukan izin produk eksplisit. Pilih Operator, Admin, atau Tanpa akses.')
        if not p['ditetapkan'] and a['mode']!='nonaktif':raise OrganisasiError('Tetapkan produk perusahaan terlebih dahulu.')
    for a in akses:
        if not products[a['produk']]['ditetapkan']:continue
        g=await db.get(AksesProdukAnggota,(company_id,user_id,a['produk']))
        if a['mode']=='warisan':
            if g:await db.delete(g)
        else:
            if g is None:g=AksesProdukAnggota(company_id=company_id,user_id=user_id,produk=a['produk']);db.add(g)
            g.aktif=a['mode']!='nonaktif';g.peran=a['mode'] if g.aktif else P.OPERATOR
    await db.flush();after=await rincian(db,ruang=ruang,company_id=company_id,user_id=user_id)
    if before['akses']!=after['akses']:
        await log_activity(db,table_name='hmu_member_products',record_id=user_id,action='UPDATE',changed_by=ruang.user_id,field_name=f'company:{company_id}:akses_produk',old_value=json.dumps(before,ensure_ascii=False),new_value=json.dumps(after,ensure_ascii=False),alasan=alasan,aksi='akses_produk')
    return after
