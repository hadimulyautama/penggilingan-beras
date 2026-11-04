"""Pisahkan tambahan kartu QC dari kontrak kartu yang sudah ada sebelumnya."""


def tanpa_kartu_qc(sumber):
    awal = "        {% elif b.aksi == 'sampel_qc_sosoh' %}"
    akhir = '        {% elif b.aksi and listview %}'
    assert sumber.count(awal) == 1
    depan, sisa = sumber.split(awal, 1)
    tambahan, belakang = sisa.split(akhir, 1)
    assert 'Buka QC penyosohan' in tambahan and '#qc-sosoh' in tambahan
    return depan + akhir + belakang
