"""FIFO pembacaan laporan; pool asal dikurangi tepat sekali per pemakaian."""
def alokasi_sumber(movements, histories, closed_at):
    events = {}
    for sid, rows in movements.items():
        events[sid] = [(t, 0, i, 'masuk', kg, source) for i,(t,_,kg,source) in enumerate(rows)]
    for u, proc in histories:
        if u.berat_akhir_kg is None:
            continue
        used = (float(u.berat_terpakai_kg) if u.berat_terpakai_kg is not None else
                float(u.berat_awal_kg) + float(u.berat_masuk_kg or 0) - float(u.berat_akhir_kg))
        t = closed_at.get(u.id) or u.updated_at or proc.waktu_selesai or proc.waktu_mulai
        events.setdefault(u.silo_id, []).append((t, 1, u.id, 'pakai', max(0, used), None))
    result = {}
    for sid, rows in events.items():
        pool = []
        for _,_,id_,kind,amount,source in sorted(rows, key=lambda e: e[:3]):
            if kind == 'masuk':
                pool.append([amount, source])
                continue
            rest, consumed = amount, []
            for item in pool:
                take = min(item[0], rest)
                if take > 0:
                    consumed.append(dict(item[1], weight=take))
                    item[0] -= take
                    rest -= take
                if rest <= .0001:
                    break
            if rest > .0001:
                consumed.append(dict(kind='legacy', code='Bahan tanpa rincian sumber', material='Bahan',
                                     owner='Tidak tercatat', plate='—', weight=rest))
            result[id_] = consumed
            pool = [x for x in pool if x[0] > .0001]
    return result
