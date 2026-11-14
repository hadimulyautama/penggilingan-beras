from app.services.console_pembatas import PembatasMasuk


def test_batas_hash_melindungi_kapasitas_operator():
    p=PembatasMasuk()
    for n in range(3):assert p.mulai(str(n)) is None
    assert p.mulai('lain')==1
    p.selesai();assert p.mulai('lain') is None


def test_anggaran_sumber_luruh_tanpa_menghapus_sumber_lain(monkeypatch):
    from app.services import console_pembatas as m
    clock=[100.0];monkeypatch.setattr(m.time,'monotonic',lambda:clock[0])
    p=PembatasMasuk()
    for _ in range(20):assert p.mulai('a') is None;p.selesai()
    assert p.mulai('a')==60
    assert p.mulai('b') is None;p.selesai()
    clock[0]+=61
    assert p.mulai('a') is None
