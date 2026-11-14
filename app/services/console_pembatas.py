"""Anggaran hash Console terpisah agar pintu login baru tidak menahan operator."""
import time
from collections import deque


class PembatasMasuk:
    def __init__(self):self.bersihkan()
    def bersihkan(self):self.aktif=0;self.jejak={}
    def mulai(self,jejak):
        now=time.monotonic()
        if self.aktif>=3:return 1
        for key in list(self.jejak):
            q=self.jejak[key]
            while q and now-q[0]>=60:q.popleft()
            if not q:del self.jejak[key]
        if jejak not in self.jejak and len(self.jejak)>=2048:return 60
        q=self.jejak.setdefault(jejak,deque())
        if len(q)>=20:return max(1,60-(now-q[0]))
        q.append(now);self.aktif+=1
        return None
    def selesai(self):self.aktif=max(0,self.aktif-1)


pembatas=PembatasMasuk()
