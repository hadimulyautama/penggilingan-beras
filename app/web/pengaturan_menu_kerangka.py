"""Structure-only proposal for native Settings index/session, without wiring.

Boolean flags must come from the exact native caller. Compiling a blueprint
is not authorization and never derives a role, recovery status or target ID.
"""
from __future__ import annotations


def _ya(flags, key):
    return flags.get(key) is True


def _pintu(href, judul, isi, ikon, allowed=True):
    return dict(href=href, judul=judul, isi=isi, ikon=ikon, allowed=allowed is True)


def kelompok_index(flags, console_url=''):
    """Same native slots/order; unknown conditional flags are locked spans."""
    groups = []
    def group(id_, title, subtitle, icon, doors):
        groups.append(dict(id=id_, title=title, subtitle=subtitle, icon=icon, doors=doors))
    group('akun', 'Akun & perangkat', 'Pribadi · perangkat ini', 'user', [
        _pintu('/pengaturan/akun', 'Nama & kata sandi', 'Nama pada catatan pekerjaan', 'user'),
        _pintu('/pengaturan/peran', 'Peran & gudang kerja', 'Lihat sebagai atau pilih gudang kerja', 'eye', _ya(flags,'blok_kerja_gudang') or _ya(flags,'blok_lihat_sebagai')),
        _pintu('/pengaturan/sesi', 'Sesi perangkat', 'Keluar atau ganti pengguna', 'device')])
    facilities = [_pintu('/pengaturan/perusahaan-sendiri', 'Perusahaan saya', 'Anggota, lokasi, gudang, dan audit perusahaan Anda', 'factory')]
    # Optional Console target is supplied by the same native caller. No URL
    # is derived from a query, a role or a fabricated environment setting.
    if _ya(flags,'blok_perusahaan') and isinstance(console_url,str) and console_url.startswith('https://'):
        facilities.append(_pintu(console_url, 'Console Center', 'Pengelolaan lintas perusahaan untuk Super Admin sistem', 'factory'))
    facilities.extend([
        _pintu('/pengaturan/perusahaan', 'Identitas & logo perusahaan', 'Nama, alamat, kontak, dan logo dokumen', 'factory',_ya(flags,'blok_perusahaan')),
        _pintu('/pengaturan/gudang', 'Gudang', 'Nama, alamat, dan geotag', 'warehouse',_ya(flags,'blok_kelola')),
        _pintu('/pengaturan/mesin', 'Mesin & line produksi', 'Pengering, penggilingan, dan penyosohan', 'factory',_ya(flags,'blok_kelola')),
        _pintu('/pengaturan/silo', 'Silo', 'Silo gabah dan bahan penyosohan', 'warehouse',_ya(flags,'blok_kelola'))])
    group('fasilitas', 'Perusahaan & fasilitas', 'Identitas, lokasi, dan sarana produksi', 'factory', facilities)
    if not (flags.get('blok_setelan') is False and flags.get('TAMPILAN_INDUK') is False):
        operation = [_pintu('/pengaturan/'+key,name,desc,icon,_ya(flags,'blok_setelan')) for key,name,desc,icon in [
            ('sebab-berhenti', 'Sebab berhenti proses', 'Pilihan sebab sesuai proses yang tersedia', 'pause'),
            ('spesifikasi-beras', 'Jenis / Spesifikasi Beras', 'Nama, kadar broken dan derajat sosoh acuan', 'sliders'),
            ('hasil-samping', 'Jenis Hasil Samping', 'Jenis dan pengemasan otomatis hasil samping', 'sliders'),
            ('mutu', 'Pencatatan mutu / QC', 'Formulir dan pengingat mutu', 'clipboard')]]
        group('operasional', 'Operasional', 'Berlaku untuk proses produksi', 'sliders', operation)
    group('pengguna', 'Pengguna & hak akses', 'Akun pengguna dan izin tindakan', 'users', [
        _pintu('/pengguna', 'Kelola pengguna', 'Orang, akun, peran, dan sandi', 'users',_ya(flags,'blok_kelola')),
        _pintu('/pengaturan/akses', 'Daftar akses', 'Hak tiap peran dan rincian setiap tindakan', 'users')])
    system = [
        _pintu('/pengaturan/kledo', 'Kontak Kledo', 'Perbarui kontak pelanggan & vendor', 'refresh',_ya(flags,'blok_setelan')),
        _pintu('/audit', 'Catatan audit', 'Catatan, pelaku, waktu, dan filter', 'history',_ya(flags,'tuan')),
        _pintu('/pengaturan/sistem', 'Batas ubah & versi', 'Informasi dan aturan aplikasi', 'info')]
    if _ya(flags,'blok_mode_uji') or _ya(flags,'mode_uji_tersedia'):
        system.append(_pintu('/pengaturan/mode-uji', 'Mode uji', 'Hapus data uji — tiket timbang tetap tersimpan', 'flask',_ya(flags,'blok_mode_uji')))
    group('sistem', 'Sistem & koneksi', 'Informasi aplikasi dan koneksi' if _ya(flags,'tuan') else 'Informasi aplikasi', 'plug', system)
    return groups


def spesifikasi(path, query='', flags=None, console_url=''):
    """No POST feedback/query, no role binding or editable settings values."""
    if query or path not in {'/pengaturan', '/pengaturan/sesi'}:
        return None
    flags = flags if isinstance(flags, dict) else {}
    spec = dict(address=path, title='Pengaturan' if path=='/pengaturan' else 'Sesi perangkat',
                variant='index' if path=='/pengaturan' else 'sesi')
    if spec['variant']=='index':
        spec.update(groups=kelompok_index(flags,console_url),
            advanced=_ya(flags,'blok_kelola'),
            recovery=_ya(flags,'kelola_darurat') and _ya(flags,'blok_kelola'))
    else:
        short = flags.get('sesi_pendek')
        spec['session_label'] = ('Ganti pengguna' if short else 'Keluar') if type(short) is bool else 'Tindakan sesi belum dibaca'
    return spec


async def kerangka(request, akun, konteks):
    """Caller owns fresh butuh_akun/flags; never replace server authority."""
    if (request.method!='GET' or akun is None or getattr(request.state,'akun',None) is not akun
            or getattr(request.state,'portal_scope',None) is not None
            or getattr(akun,'harus_ganti_sandi',None) is not False):
        return None
    spec=spesifikasi(request.url.path,request.url.query,konteks.get('PENGATURAN_NATIVE_FLAGS'),konteks.get('console_url',''))
    shell=konteks.get('SHELL',{})
    if (spec is None or shell.get('data_url')!=spec['address']
            or not isinstance(shell.get('stamp'),str) or not shell['stamp']):
        return None
    from app.web.tampilan import render
    response=render(request,'pengaturan_menu_kerangka.html',
        **{**konteks,'layar':'pengaturan','PG_MENU_SHELL':{**spec,'stamp':shell['stamp']}})
    response.headers['Cache-Control']='private, no-store'
    response.headers['Vary']='Cookie'
    return response
