"""Satu kontainer: satu pekerja latar, beberapa proses web, berhenti bersama.

Tidak menambah replika Railway. Status Kledo dimiliki pekerja loopback;
penanda cache memakai direktori temporer bersama di kontainer yang sama.
"""
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request


def jalankan():
    jumlah=int(os.environ.get('WEB_CONCURRENCY','4'))
    if not 1<=jumlah<=4:raise ValueError('WEB_CONCURRENCY harus 1 sampai 4')
    port=int(os.environ.get('HMU_PEKERJA_PORT','8787'))
    if not 1024<=port<=65535:raise ValueError('Port pekerja tidak sah')
    children=[]
    stop=False
    def hentikan(*_):
        nonlocal stop
        stop=True
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,hentikan)
    with tempfile.TemporaryDirectory(prefix='hmu-cache-') as directory:
        shared={**os.environ,'HMU_PEKERJA_PORT':str(port),'HMU_PEKERJA_TOKEN':secrets.token_urlsafe(32),
            'HMU_CACHE_EPOCH':os.path.join(directory,'epoch')}
        try:
            worker=subprocess.Popen([sys.executable,'-m','uvicorn','app.pekerja:app','--host','127.0.0.1',
                '--port',str(port),'--log-level','warning'],env={**shared,'PERAN_PROSES':'pekerja','DB_POOL_SIZE':'2','DB_MAX_OVERFLOW':'3'})
            children.append(worker)
            deadline=time.monotonic()+90
            ready=False
            # Web belum menerima lalu lintas sebelum seed dan pekerja siap.
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while not stop and time.monotonic()<deadline:
                if worker.poll() is not None:raise RuntimeError('Pekerja gagal saat startup')
                try:
                    req=urllib.request.Request(f'http://127.0.0.1:{port}/health',headers={'X-Pekerja-Token':shared['HMU_PEKERJA_TOKEN']})
                    with opener.open(req,timeout=1) as response:ready=response.status==200
                    if ready:break
                except OSError:pass
                time.sleep(.2)
            if stop:return 0
            if not ready:raise RuntimeError('Pekerja belum siap dalam 90 detik')
            web=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','0.0.0.0',
                '--port',os.environ.get('PORT','8000'),'--log-level','warning','--workers',str(jumlah)],env={**shared,'PERAN_PROSES':'web'})
            children.append(web)
            while not stop:
                for child in children:
                    if child.poll() is not None:raise RuntimeError('Proses layanan berhenti; restart seluruh kontainer')
                time.sleep(.25)
            return 0
        finally:
            for child in children:
                if child.poll() is None:child.terminate()
            for child in children:
                try:child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill();child.wait()

if __name__=='__main__':raise SystemExit(jalankan())
