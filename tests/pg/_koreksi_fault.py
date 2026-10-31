"""Server uji UI: respons satu penyimpanan sukses diganti 503 setelah commit.

Jangan dipakai aplikasi produksi. Hanya dapat dimulai dengan flag eksplisit
dan database uji loopback. Tidak mengubah transaksi/domain layanan.
"""
import json
import os
from urllib.parse import urlparse
from app.main import app as asli

target=urlparse(os.environ.get('DATABASE_URL',''))
assert os.environ.get('KOREKSI_UJI_FAULT')=='1'
assert target.hostname in ('127.0.0.1','localhost') and target.path.startswith('/uji_')


class SatuResponsHilang:
    def __init__(self):self.selesai=False

    async def __call__(self,scope,receive,send):
        if (scope['type']!='http' or self.selesai or scope.get('method')!='POST'
                or not scope.get('path','').startswith('/api/actions/koreksi-pengiriman/')
                or not scope['path'].endswith('/simpan')):
            return await asli(scope,receive,send)
        messages=[]
        async def simpan(message):messages.append(message)
        await asli(scope,receive,simpan)
        start=next((m for m in messages if m['type']=='http.response.start'),None)
        if start and 200<=start['status']<300:
            self.selesai=True
            body=json.dumps({'detail':'Gangguan jawaban sintetis setelah komit; periksa status permintaan.'}).encode()
            await send({'type':'http.response.start','status':503,'headers':[(b'content-type',b'application/json'),(b'cache-control',b'no-store')]})
            await send({'type':'http.response.body','body':body})
        else:
            for message in messages:await send(message)


app=SatuResponsHilang()
