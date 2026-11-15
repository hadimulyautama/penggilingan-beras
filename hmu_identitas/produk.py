"""Satu kebijakan produk untuk Console, sesi PadiFlow dan sesi TeraFlow.

Ruang operasional selalu berasal konfigurasi server. Pilihan company_id dari
formulir tidak mengalihkan koneksi transaksi. Tidak menulis ORM/kredensial.
"""
from dataclasses import dataclass
from sqlalchemy import select
from hmu_core import Perusahaan,User,KeanggotaanPerusahaan,ProdukAplikasiPerusahaan,AksesProdukAnggota,IntegrasiProdukPerusahaan
from . import peran as P
from .ruang_data import RuangData

PADIFLOW='padiflow'
TERAFLOW='teraflow'
INTEGRASI='padiflow_teraflow'

@dataclass(frozen=True)
class DefinisiProduk:
    kode:str
    nama:str
    aplikasi:tuple[str,...]

KATALOG=(DefinisiProduk(PADIFLOW,'PadiFlow',('padiflow','portal')),DefinisiProduk(TERAFLOW,'TeraFlow',('teraflow',)))
KODE=tuple(x.kode for x in KATALOG)
PERAN=(P.OPERATOR,P.ADMIN)

class ProdukDitolak(PermissionError):pass

@dataclass(frozen=True)
class HakProduk:
    company_id:int|None
    produk:str
    peran:str
    sumber:str

async def perusahaan_aktif(db,company_id,produk):
    if type(company_id) is not int or not 0<company_id<=2147483647 or produk not in KODE:raise ProdukDitolak('Identitas perusahaan atau produk tidak valid.')
    with db.no_autoflush:
        co=await db.scalar(select(Perusahaan).where(Perusahaan.id==company_id).execution_options(populate_existing=True))
        row=await db.scalar(select(ProdukAplikasiPerusahaan).where(ProdukAplikasiPerusahaan.company_id==company_id,ProdukAplikasiPerusahaan.produk==produk).execution_options(populate_existing=True))
    if not co or not co.aktif or not row or not row.aktif:raise ProdukDitolak('Produk '+produk+' tidak diaktifkan untuk perusahaan ini. Hubungi Admin Sistem.')
    return row

async def hak_pengguna(db,*,company_id,produk,user_id,peran_warisan=None):
    with db.no_autoflush:
        active=await perusahaan_aktif(db,company_id,produk)
        user=await db.scalar(select(User).where(User.id==user_id).execution_options(populate_existing=True))
        if not user or (user.status or '').lower()!='aktif':raise ProdukDitolak('Pengguna aktif tidak tersedia.')
        if P.super_saja(user.role):return HakProduk(company_id,produk,P.SUPERADMIN,'platform')
        grant=await db.scalar(select(AksesProdukAnggota).where(AksesProdukAnggota.company_id==company_id,AksesProdukAnggota.user_id==user_id,AksesProdukAnggota.produk==produk).execution_options(populate_existing=True))
        if grant is not None:
            member=await db.scalar(select(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.company_id==company_id,KeanggotaanPerusahaan.user_id==user_id).execution_options(populate_existing=True))
            if not grant.aktif or not member or not member.aktif or grant.peran not in PERAN:raise ProdukDitolak('Akses pengguna ke '+produk+' tidak aktif.')
            return HakProduk(company_id,produk,grant.peran,'eksplisit')
        # HMU ditandai oleh migrasi dari dua bukti penetapan, bukan fallback
        # seluruh perusahaan. Override nonaktif selalu menang atas warisan.
        memberships=list(await db.scalars(select(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.user_id==user_id).execution_options(populate_existing=True)))
        # Kompatibilitas tanpa penetapan anggota hanya untuk akun lama.
        # Setelah keanggotaan dicatat, pencabutan eksplisit harus menang
        # atas peran master, walau belum ada override izin produk.
        member=next((m for m in memberships if m.company_id==company_id),None)
        if member is not None and not member.aktif:
            raise ProdukDitolak('Keanggotaan pengguna pada perusahaan ini tidak aktif.')
        foreign=any(m.company_id!=company_id for m in memberships)
        if foreign:
            raise ProdukDitolak('Pengguna lintas perusahaan memerlukan penetapan akses produk secara eksplisit.')
        legacy=P.normal(peran_warisan) if peran_warisan is not None else P.normal(user.role)
        if active.warisan and legacy in PERAN:return HakProduk(company_id,produk,legacy,'warisan')
    raise ProdukDitolak('Pengguna belum diberi akses ke '+produk+'.')

async def hak_lokal(db,*,produk,user_id,peran_lama=''):
    ruang=RuangData.lingkungan()
    if ruang is None:
        # Mode pengembangan lama tanpa ruang tenant; bukan jalur produksi.
        return HakProduk(None,produk,P.normal(peran_lama),'tanpa_ruang')
    if user_id is not None:return await hak_pengguna(db,company_id=ruang.company_id,produk=produk,user_id=user_id,peran_warisan=peran_lama)
    row=await perusahaan_aktif(db,ruang.company_id,produk)
    if row.warisan and P.sah(peran_lama):return HakProduk(ruang.company_id,produk,P.normal(peran_lama),'profil_lama')
    raise ProdukDitolak('Tautkan akun ke keanggotaan perusahaan dan tetapkan akses produk terlebih dahulu.')

async def produk_lokal(db,produk):
    ruang=RuangData.lingkungan()
    return await perusahaan_aktif(db,ruang.company_id,produk) if ruang else None

async def integrasi_lokal(db):
    ruang=RuangData.lingkungan()
    if not ruang:return
    with db.no_autoflush:
        for kode in KODE:await perusahaan_aktif(db,ruang.company_id,kode)
        row=await db.scalar(select(IntegrasiProdukPerusahaan).where(IntegrasiProdukPerusahaan.company_id==ruang.company_id,IntegrasiProdukPerusahaan.kode==INTEGRASI).execution_options(populate_existing=True))
    if not row or not row.aktif:raise ProdukDitolak('Integrasi PadiFlow–TeraFlow tidak diaktifkan untuk perusahaan ini.')
