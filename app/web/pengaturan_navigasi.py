"""Alamat rincian Pengaturan; tidak menerima alamat kembali bebas."""
HALAMAN = {
    'akses': ('Akses pengguna', 'Daftar akses'),
    'akun': ('Akun & perangkat', 'Nama & kata sandi'),
    'peran': ('Akun & perangkat', 'Gudang kerja dan tampilan peran'),
    'sesi': ('Akun & perangkat', 'Sesi perangkat'),
    'sebab-berhenti': ('Operasional', 'Sebab berhenti proses'),
    'mutu': ('Operasional', 'Pencatatan mutu / QC'),
    'kledo': ('Sistem & koneksi', 'Kontak Kledo'),
    'sistem': ('Sistem & koneksi', 'Batas ubah & versi'),
}


def kembali(nilai, bawaan='/pengaturan'):
    return nilai if nilai in {f'/pengaturan/{k}' for k in HALAMAN} else bawaan


async def tujuan_form(request, bawaan='/pengaturan'):
    return kembali((await request.form()).get('kembali_pengaturan'), bawaan)
