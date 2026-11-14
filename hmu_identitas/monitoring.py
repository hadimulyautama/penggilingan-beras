"""Metadata monitoring dan bantuan; tidak memetakan ulang transaksi pabrik."""
from dataclasses import dataclass
from datetime import datetime,timezone
import asyncio,logging,time,uuid
from sqlalchemy import text,Boolean,DateTime,ForeignKey,Index,String,Text,UniqueConstraint,func,select
from sqlalchemy.orm import Mapped,mapped_column
from hmu_core import Base
from .ruang_data import RuangData


class SumberMonitoring(Base):
    __tablename__='hmu_monitoring_sources'
    company_id:Mapped[int]=mapped_column(ForeignKey('hmu_companies.id'),primary_key=True)
    aplikasi:Mapped[str]=mapped_column(String(16),primary_key=True)
    mulai:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    terakhir:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    versi:Mapped[str]=mapped_column(String(64),default='')


class KejadianPemakaian(Base):
    __tablename__='hmu_usage_events'
    __table_args__=(UniqueConstraint('company_id','aplikasi','event_id',name='uq_hmu_usage_event'),
        Index('ix_hmu_usage_time','company_id','waktu'),Index('ix_hmu_usage_subject','company_id','jenis_akun','akun_id','waktu'))
    id:Mapped[int]=mapped_column(primary_key=True)
    company_id:Mapped[int]=mapped_column(ForeignKey('hmu_companies.id'))
    aplikasi:Mapped[str]=mapped_column(String(16))
    event_id:Mapped[str]=mapped_column(String(36))
    jenis_akun:Mapped[str]=mapped_column(String(20))
    akun_id:Mapped[int]=mapped_column(default=0)
    user_id:Mapped[int|None]=mapped_column(nullable=True)
    peran:Mapped[str]=mapped_column(String(24),default='')
    warehouse_id:Mapped[int|None]=mapped_column(nullable=True)
    jenis:Mapped[str]=mapped_column(String(24))
    layar:Mapped[str]=mapped_column(String(40),default='lainnya')
    kode:Mapped[str]=mapped_column(String(40),default='')
    metode:Mapped[str]=mapped_column(String(8),default='')
    browser:Mapped[str]=mapped_column(String(20),default='lainnya')
    perangkat:Mapped[str]=mapped_column(String(20),default='lainnya')
    durasi_ms:Mapped[int|None]=mapped_column(nullable=True)
    waktu:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())


class PembukaanMasuk(Base):
    __tablename__='hmu_login_unlocks'
    company_id:Mapped[int]=mapped_column(ForeignKey('hmu_companies.id'),primary_key=True)
    jenis_akun:Mapped[str]=mapped_column(String(20),primary_key=True)
    akun_id:Mapped[int]=mapped_column(primary_key=True)
    generasi:Mapped[int]=mapped_column(default=0)


class RencanaBantuan(Base):
    __tablename__='hmu_support_plans'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    company_id:Mapped[int]=mapped_column(ForeignKey('hmu_companies.id'))
    pelaku_id:Mapped[int]=mapped_column(ForeignKey('users.id'))
    jenis_akun:Mapped[str]=mapped_column(String(20))
    akun_id:Mapped[int]=mapped_column()
    aksi:Mapped[str]=mapped_column(String(32))
    alasan:Mapped[str]=mapped_column(Text)
    sidik:Mapped[str]=mapped_column(String(64))
    sebelum:Mapped[str]=mapped_column(Text)
    kedaluwarsa:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    diterapkan:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    hasil:Mapped[str|None]=mapped_column(Text)


class PemulihanAkun(Base):
    __tablename__='hmu_account_recoveries'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    company_id:Mapped[int]=mapped_column(ForeignKey('hmu_companies.id'))
    jenis_akun:Mapped[str]=mapped_column(String(20))
    akun_id:Mapped[int]=mapped_column()
    cap_hash:Mapped[str]=mapped_column(String(64),unique=True)
    versi:Mapped[int]=mapped_column()
    kedaluwarsa:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    dipakai:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    dicabut:Mapped[bool]=mapped_column(Boolean,default=False)
    pelaku_id:Mapped[int]=mapped_column(ForeignKey('users.id'))


@dataclass(frozen=True)
class PelakuPemakaian:
    jenis_akun:str
    akun_id:int
    user_id:int|None=None
    peran:str=''
    warehouse_id:int|None=None


def perangkat_dari(ua):
    ua=(ua or '').lower()
    browser='edge' if 'edg/' in ua else 'chrome' if ('chrome/' in ua or 'crios/' in ua) else 'firefox' if 'firefox/' in ua else 'safari' if 'safari/' in ua else 'lainnya'
    perangkat='iphone' if 'iphone' in ua else 'ipad' if 'ipad' in ua else 'android' if 'android' in ua else 'desktop'
    return browser,perangkat


def layar_dari(path):
    parts=(path or '').split('/')
    for key in ('stok','pekerjaan','barang-masuk','pengiriman','pengaturan','laporan','timbang','tiket','daftar','giling','sosoh','retur','masuk','ganti-sandi'):
        if any(x==key or x.startswith(key+'-') for x in parts):return key
    return 'beranda' if path in ('/','/pelanggan/','/timbangan/') else 'lainnya'


class PengumpulPemakaian:
    """Antrean terbatas; kegagalan statistik tidak ditunggu oleh transaksi bisnis."""
    def __init__(self,sesi,aplikasi,versi=''):
        self.sesi=sesi;self.aplikasi=aplikasi;self.versi=versi[:64]
        self.antrean=asyncio.Queue(maxsize=4096);self.tugas=None;self.dibuang=0;self._batas={}
        self.log=logging.getLogger('monitoring')

    def catat(self,pelaku,*,jenis,layar='lainnya',kode='',ua='',durasi_ms=None,event_id=None,metode=''):
        ruang=RuangData.lingkungan()
        if not ruang:return False
        if jenis in ('interaksi','galat_browser'):
            slot=int(time.monotonic()//60);key=(pelaku.jenis_akun,pelaku.akun_id,jenis,slot)
            if self._batas.get(key,0)>=16:return False
            if len(self._batas)>8192:self._batas={k:v for k,v in self._batas.items() if k[-1]==slot}
            self._batas[key]=self._batas.get(key,0)+1
        browser,perangkat=perangkat_dari(ua)
        data=dict(company_id=ruang.company_id,aplikasi='portal' if pelaku.jenis_akun=='pelanggan' else self.aplikasi,event_id=event_id or str(uuid.uuid4()),
            jenis_akun=pelaku.jenis_akun,akun_id=pelaku.akun_id,user_id=pelaku.user_id,peran=pelaku.peran,
            warehouse_id=pelaku.warehouse_id,jenis=jenis,layar=layar,kode=kode[:40],metode=metode[:8],browser=browser,perangkat=perangkat,
            durasi_ms=min(max(int(durasi_ms),0),3600000) if durasi_ms is not None else None,
            waktu=datetime.now(timezone.utc))
        try:self.antrean.put_nowait(data);return True
        except asyncio.QueueFull:self.dibuang+=1;return False

    async def kirim(self):
        from sqlalchemy.dialects.postgresql import insert
        ruang=RuangData.lingkungan()
        if not ruang:return
        batch=[]
        while len(batch)<200:
            try:batch.append(self.antrean.get_nowait())
            except asyncio.QueueEmpty:break
        try:
            async with self.sesi() as db:
                await db.execute(text("SET LOCAL statement_timeout='1500ms'"))
                now=datetime.now(timezone.utc)
                for aplikasi in (('padiflow','portal') if self.aplikasi=='padiflow' else (self.aplikasi,)):
                    stmt=insert(SumberMonitoring).values(company_id=ruang.company_id,aplikasi=aplikasi,versi=self.versi,mulai=now,terakhir=now)
                    await db.execute(stmt.on_conflict_do_update(index_elements=['company_id','aplikasi'],set_=dict(terakhir=now,versi=self.versi)))
                if batch:
                    await db.execute(insert(KejadianPemakaian).values(batch).on_conflict_do_nothing(constraint='uq_hmu_usage_event'))
                await db.commit()
        except Exception:
            # Tidak menulis payload, nama pengguna, URL, IP, atau rahasia ke log.
            self.log.warning('Pengiriman metadata monitoring tertunda')
            for item in batch:
                if (datetime.now(timezone.utc)-item['waktu']).total_seconds()>300:self.dibuang+=1;continue
                try:self.antrean.put_nowait(item)
                except asyncio.QueueFull:self.dibuang+=1

    async def jalan(self):
        while True:
            await self.kirim();await asyncio.sleep(10)

    def mulai(self):
        if self.tugas is None:self.tugas=asyncio.create_task(self.jalan())

    async def tutup(self):
        from contextlib import suppress
        if self.tugas:
            self.tugas.cancel()
            with suppress(asyncio.CancelledError):await self.tugas
            self.tugas=None
        try:await asyncio.wait_for(self.kirim(),timeout=2)
        except Exception:pass


class MonitoringHTTP:
    """Dipasang sebelum middleware kompresi; menyisipkan skrip tanpa menahan HTML.

    Hanya ekor 32 byte yang ditahan. Formulir, skrip aplikasi dan aliran SSE
    tetap lewat; tidak ada penggantian DOM oleh monitoring.
    """
    def __init__(self,app,*,pengumpul,pelaku,skrip='/monitoring/aktivitas.js'):
        self.app=app;self.pengumpul=pengumpul;self.pelaku=pelaku;self.skrip=skrip
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        path=scope.get('path','');method=scope.get('method','GET')
        skip=any(x in path for x in ('/monitoring','/static/','/health','/internal/','/pemulihan','/api/aliran'))
        started=time.monotonic();status=500;dicatat=False;html=False;tail=b''
        async def kirim(msg):
            nonlocal status,dicatat,html,tail
            if msg['type']=='http.response.start':
                status=msg['status'];headers=msg.get('headers',[])
                state=scope.get('state',{})
                html=(not skip and method=='GET' and status==200 and RuangData.lingkungan() is not None
                    and bool(state.get('akun') or state.get('portal_account'))
                    and any(k.lower()==b'content-type' and v.startswith(b'text/html') for k,v in headers))
                if html:msg={**msg,'headers':[(k,v) for k,v in headers if k.lower()!=b'content-length']}
            if msg['type']=='http.response.body':
                if not skip and not dicatat and not msg.get('more_body',False):
                    dicatat=True
                    if method in ('POST','PUT','PATCH','DELETE') or status>=500:
                        actor=self.pelaku(scope.get('state',{})) or PelakuPemakaian('anonim',0)
                        ua=dict(scope.get('headers',[])).get(b'user-agent',b'').decode('latin1')
                        try:self.pengumpul.catat(actor,jenis='respons_web',layar=layar_dari(path),kode=str(status),ua=ua,durasi_ms=(time.monotonic()-started)*1000,metode=method)
                        except Exception:pass
                if html:
                    body=tail+msg.get('body',b'')
                    if msg.get('more_body',False):
                        tail=body[-32:];msg={**msg,'body':body[:-32]}
                    else:
                        script=('<script src="'+self.skrip+'" defer></script>').encode()
                        body=body.replace(b'</body>',script+b'</body>') if b'</body>' in body else body+script
                        msg={**msg,'body':body}
            await send(msg)
        try:return await self.app(scope,receive,kirim)
        except Exception:
            if not skip and not dicatat:
                actor=self.pelaku(scope.get('state',{})) or PelakuPemakaian('anonim',0)
                try:self.pengumpul.catat(actor,jenis='respons_web',layar=layar_dari(path),kode='500',durasi_ms=(time.monotonic()-started)*1000,metode=method)
                except Exception:pass
            raise
