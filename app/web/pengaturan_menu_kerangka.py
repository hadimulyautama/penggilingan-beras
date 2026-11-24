"""Structure-only proposal for native Settings index/session, without wiring.

Boolean flags must come from the exact native caller. Compiling a blueprint
is not authorization and never derives a role, recovery status or target ID.
"""
from __future__ import annotations


def _ya(flags, key):
    return flags.get(key) is True


def _pintu(href, judul, isi, ikon):
    return dict(href=href, judul=judul, isi=isi, ikon=ikon)


def kelompok_index(flags):
    """Native groups/door order. Unknown conditional metadata denies doors."""
    groups = []
    def group(id_, title, subtitle, icon, doors):
        groups.append(dict(id=id_, title=title, subtitle=subtitle, icon=icon, doors=doors))
    own = [_pintu('/pengaturan/akun', 'Nama & kata sandi', 'Nama pada catatan pekerjaan', 'user')]
    if _ya(flags, 'blok_kerja_gudang') or _ya(flags, 'blok_lihat_sebagai'):
        own.append(_pintu('/pengaturan/peran', 'Peran & gudang kerja', 'Lihat sebagai atau pilih gudang kerja', 'eye'))
    own.append(_pintu('/pengaturan/sesi', 'Sesi perangkat', 'Keluar atau ganti pengguna', 'device'))
    group('akun', 'Akun & perangkat', 'Pribadi · perangkat ini', 'user', own)
    facilities = [_pintu('/pengaturan/perusahaan-sendiri', 'Perusahaan saya', 'Anggota, lokasi, gudang, dan audit perusahaan Anda', 'factory')]
    if _ya(flags, 'blok_perusahaan') and _ya(flags, 'console_configured'):
        facilities.append(_pintu(None, 'Console Center', 'Pengelolaan lintas perusahaan untuk Super Admin sistem', 'factory'))
    if _ya(flags, 'blok_perusahaan'):
        facilities.append(_pintu('/pengaturan/perusahaan', 'Identitas & logo perusahaan', 'Nama, alamat, kontak, dan logo dokumen', 'factory'))
    if _ya(flags, 'blok_kelola'):
        facilities.extend([_pintu('/pengaturan/gudang', 'Gudang', 'Nama, alamat, dan geotag', 'warehouse'),
            _pintu('/pengaturan/mesin', 'Mesin & line produksi', 'Pengering, penggilingan, dan penyosohan', 'factory'),
            _pintu('/pengaturan/silo', 'Silo', 'Silo gabah dan bahan penyosohan', 'warehouse')])
    group('fasilitas', 'Perusahaan & fasilitas', 'Identitas, lokasi, dan sarana produksi', 'factory', facilities)
    if _ya(flags, 'blok_setelan') or _ya(flags, 'TAMPILAN_INDUK'):
        operation = []
        if _ya(flags, 'blok_setelan'):
            operation = [_pintu('/pengaturan/'+key, name, desc, icon) for key,name,desc,icon in [
                ('sebab-berhenti', 'Sebab berhenti proses', 'Pilihan sebab sesuai proses yang tersedia', 'pause'),
                ('spesifikasi-beras', 'Jenis / Spesifikasi Beras', 'Nama, kadar broken dan derajat sosoh acuan', 'sliders'),
                ('hasil-samping', 'Jenis Hasil Samping', 'Jenis dan pengemasan otomatis hasil samping', 'sliders'),
                ('mutu', 'Pencatatan mutu / QC', 'Formulir dan pengingat mutu', 'clipboard')]]
        group('operasional', 'Operasional', 'Berlaku untuk proses produksi', 'sliders', operation)
    users = []
    if _ya(flags, 'blok_kelola'):
        users.append(_pintu('/pengguna', 'Kelola pengguna', 'Orang, akun, peran, dan sandi', 'users'))
    users.append(_pintu('/pengaturan/akses', 'Daftar akses', 'Hak tiap peran dan rincian setiap tindakan', 'users'))
    group('pengguna', 'Pengguna & hak akses', 'Akun pengguna dan izin tindakan', 'users', users)
    system = []
    if _ya(flags, 'blok_setelan'):
        system.append(_pintu('/pengaturan/kledo', 'Kontak Kledo', 'Perbarui kontak pelanggan & vendor', 'refresh'))
    if _ya(flags, 'tuan'):
        system.append(_pintu('/audit', 'Catatan audit', 'Catatan, pelaku, waktu, dan filter', 'history'))
    system.append(_pintu('/pengaturan/sistem', 'Batas ubah & versi', 'Informasi dan aturan aplikasi', 'info'))
    if _ya(flags, 'blok_mode_uji'):
        system.append(_pintu('/pengaturan/mode-uji', 'Mode uji', 'Hapus data uji — tiket timbang tetap tersimpan', 'flask'))
    group('sistem', 'Sistem & koneksi', 'Informasi aplikasi dan koneksi' if _ya(flags, 'tuan') else 'Informasi aplikasi', 'plug', system)
    return groups


def spesifikasi(path, query='', flags=None):
    """No POST feedback/query, no role binding or editable settings values."""
    if query or path not in {'/pengaturan', '/pengaturan/sesi'}:
        return None
    flags = flags if isinstance(flags, dict) else {}
    spec = dict(address=path, title='Pengaturan' if path=='/pengaturan' else 'Sesi perangkat',
                variant='index' if path=='/pengaturan' else 'sesi')
    if spec['variant']=='index':
        spec.update(groups=kelompok_index(flags),
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
    spec=spesifikasi(request.url.path,request.url.query,konteks.get('PENGATURAN_NATIVE_FLAGS'))
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
