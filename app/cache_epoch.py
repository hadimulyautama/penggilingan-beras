"""Invalidasi cache antarproses dalam SATU kontainer, tanpa data bisnis.

Supervisor memberi direktori privat yang sama ke web dan pekerja. Commit
mengganti inode marker secara atomik. Pembaca memeriksa marker sebelum
memakai snapshot; cookie/izin tidak pernah disimpan di sini.
"""
import logging
import os
import tempfile

log=logging.getLogger('cache_epoch')
_terakhir={}


def berubah():
    path=os.environ.get('HMU_CACHE_EPOCH')
    if not path:return False
    try:
        st=os.stat(path)
        token=(st.st_ino,st.st_mtime_ns)
    except FileNotFoundError:token=None
    except OSError:
        return True  # Marker tak dapat dibaca: lewati cache dengan mengosongkannya.
    lama=_terakhir.get(path)
    _terakhir[path]=token
    return token!=lama


def catat():
    path=os.environ.get('HMU_CACHE_EPOCH')
    if not path:return
    temporary=None
    try:
        fd,temporary=tempfile.mkstemp(dir=os.path.dirname(path),prefix='.epoch-')
        os.close(fd)
        os.replace(temporary,path)
    except OSError:
        # Commit SQL sudah sukses. Jangan mengaku transaksi gagal karena
        # gangguan filesystem; TTL singkat tetap menjadi batas cadangan.
        log.exception('Marker invalidasi cache tidak dapat diperbarui')
    finally:
        if temporary and os.path.exists(temporary):os.unlink(temporary)
