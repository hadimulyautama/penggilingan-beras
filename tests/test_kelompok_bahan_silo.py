from app.services.proses_aktif import kelompok_bahan_silo


def test_silo_dipakai_ulang_tetap_terpisah_dan_asal_bukan_alokasi():
    rows = [('Silo A', '7.500 kg', 'Dilepaskan · kosong, siap diisi', 'dibebaskan'),
            ('PK', '7.500 kg', '', 'sosoh-bahan'),
            ('LOT-01', '7.500 kg', '', 'lot-dibebaskan'),
            ('Silo A', '2.000 kg', 'Aktif · masih dipakai proses', 'silo'),
            ('PK', '2.000 kg', '', 'sosoh-bahan'),
            ('LOT-01', '7.500 kg', '', 'lot'),
            ('LOT-02', '2.000 kg', '', 'lot')]
    original = list(rows)
    groups = kelompok_bahan_silo(rows)
    assert len(groups) == 2
    assert [g['berat'] for g in groups] == ['7.500 kg', '2.000 kg']
    assert groups[0]['status'] == 'Dilepaskan pada pemakaian ini · sisa 0 kg'
    assert groups[1]['sumber'][0]['berat'] == '7.500 kg'
    assert len(groups[1]['sumber']) == 2
    assert rows == original
